#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "voice_kws.h"

/*
 * Host driver for the int8 inference engine.
 *
 *   test_voice_kws_c.exe <features.bin> <logits.bin>
 *
 * features.bin : N * VOICE_MODEL_INPUT_COUNT int8, row major
 * logits.bin   : N * VOICE_MODEL_CLASS_COUNT int8, written by this program
 *
 * tests/test_voice_kws.py generates the input, runs the TFLite reference on the
 * same bytes, and compares. Keep the file format in sync with that parser.
 *
 * Also runs self-contained assertions so a bare invocation still means
 * something without TensorFlow present.
 */

static voice_kws_t g_kws;

static void test_argmax(void)
{
    const int8_t a[6] = {-5, 3, 3, 9, 0, -1};
    const int8_t b[6] = {-128, -128, -128, -128, -128, -128};
    const int8_t c[6] = {1, 2, 3, 4, 5, 6};
    assert(voice_kws_argmax(a) == 3);
    assert(voice_kws_argmax(b) == 0); /* ties resolve to the lowest index */
    assert(voice_kws_argmax(c) == 5);
    assert(voice_kws_argmax(NULL) == -1);
}

static void test_probabilities(void)
{
    float p[VOICE_MODEL_CLASS_COUNT];
    int8_t logits[VOICE_MODEL_CLASS_COUNT];
    float total = 0.0f;
    uint32_t i;

    for (i = 0U; i < VOICE_MODEL_CLASS_COUNT; ++i)
    {
        logits[i] = (int8_t)(i * 10);
    }
    voice_kws_probabilities(logits, p);

    for (i = 0U; i < VOICE_MODEL_CLASS_COUNT; ++i)
    {
        assert(p[i] >= 0.0f && p[i] <= 1.0f);
        total += p[i];
    }
    assert(fabsf(total - 1.0f) < 1.0e-4f);
    /* Highest logit must also be the highest probability. */
    {
        uint32_t best = 0U;
        for (i = 1U; i < VOICE_MODEL_CLASS_COUNT; ++i)
        {
            if (p[i] > p[best])
            {
                best = i;
            }
        }
        assert(best == VOICE_MODEL_CLASS_COUNT - 1U);
    }
}

static void test_uniform_input_is_deterministic(void)
{
    static int8_t features[VOICE_MODEL_INPUT_COUNT];
    int8_t first[VOICE_MODEL_CLASS_COUNT];
    int8_t second[VOICE_MODEL_CLASS_COUNT];

    memset(features, 0, sizeof(features));
    assert(voice_kws_run(&g_kws, features) == 0);
    memcpy(first, g_kws.logits, sizeof(first));
    assert(voice_kws_run(&g_kws, features) == 0);
    memcpy(second, g_kws.logits, sizeof(second));
    assert(memcmp(first, second, sizeof(first)) == 0);
}

static void test_null_safety(void)
{
    assert(voice_kws_run(NULL, NULL) == -1);
    assert(voice_kws_run(&g_kws, NULL) == -1);
    voice_kws_init(NULL);
    voice_kws_probabilities(NULL, NULL);
}


static void test_run_until_reports_exact_layer_sizes(void)
{
    /*
     * Regression guard. voice_kws_run_until() is the hook the layer-by-layer
     * TFLite comparison uses. An earlier revision derived the element count
     * from a chain of comparisons on stop_after and got layers 4, 5 and 6
     * wrong, so a caller passing an exactly-sized buffer got -1 (a false
     * failure) and a caller passing a larger buffer got stale bytes from the
     * layer below. Nothing caught it because no test called the function.
     */
    static int8_t features[VOICE_MODEL_INPUT_COUNT];
    static int8_t out[VOICE_MODEL_L0_OUT_COUNT];
    static const uint32_t expected[VOICE_MODEL_LAYER_COUNT] = {
        VOICE_MODEL_L0_OUT_COUNT, VOICE_MODEL_L1_OUT_COUNT,
        VOICE_MODEL_L2_OUT_COUNT, VOICE_MODEL_L3_OUT_COUNT,
        VOICE_MODEL_L4_OUT_COUNT, VOICE_MODEL_L5_OUT_COUNT,
        VOICE_MODEL_L6_OUT_COUNT, VOICE_MODEL_L7_OUT_COUNT,
    };
    uint32_t layer;

    memset(features, 0, sizeof(features));

    for (layer = 0U; layer < (uint32_t)VOICE_MODEL_LAYER_COUNT; ++layer)
    {
        /* Exactly-sized buffer must succeed, not report a false failure. */
        assert(voice_kws_run_until(&g_kws, features, layer, out, expected[layer]) ==
               (int)expected[layer]);

        /* One byte short must be refused rather than truncated. */
        assert(voice_kws_run_until(&g_kws, features, layer, out,
                                   expected[layer] - 1U) == -1);
    }

    /* Out-of-range layer index is refused. */
    assert(voice_kws_run_until(&g_kws, features, (uint32_t)VOICE_MODEL_LAYER_COUNT,
                               out, sizeof(out)) == -1);
}

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *file = fopen(path, "rb");
    long size;
    uint8_t *data;

    if (file == NULL)
    {
        return NULL;
    }
    if (fseek(file, 0L, SEEK_END) != 0)
    {
        fclose(file);
        return NULL;
    }
    size = ftell(file);
    if (size < 0)
    {
        fclose(file);
        return NULL;
    }
    rewind(file);
    data = (uint8_t *)malloc((size_t)size);
    if (data == NULL)
    {
        fclose(file);
        return NULL;
    }
    if (fread(data, 1U, (size_t)size, file) != (size_t)size)
    {
        free(data);
        fclose(file);
        return NULL;
    }
    fclose(file);
    *out_size = (size_t)size;
    return data;
}

int main(int argc, char **argv)
{
    voice_kws_init(&g_kws);
    assert(g_kws.initialized == 1U);

    test_argmax();
    test_probabilities();
    test_uniform_input_is_deterministic();
    test_run_until_reports_exact_layer_sizes();
    test_null_safety();

    if (argc > 1)
    {
        size_t in_size = 0U;
        uint8_t *input;
        size_t sample_count;
        int8_t *logits;
        FILE *out;
        size_t i;

        if (argc != 3)
        {
            fprintf(stderr, "usage: %s <features.bin> <logits.bin>\n", argv[0]);
            return 2;
        }

        input = read_file(argv[1], &in_size);
        if (input == NULL)
        {
            fprintf(stderr, "cannot read %s\n", argv[1]);
            return 2;
        }
        if ((in_size % VOICE_MODEL_INPUT_COUNT) != 0U)
        {
            /* MinGW's printf has no %zu; cast instead. */
            fprintf(stderr, "%u bytes is not a multiple of %u features\n",
                    (unsigned)in_size, (unsigned)VOICE_MODEL_INPUT_COUNT);
            free(input);
            return 2;
        }

        sample_count = in_size / VOICE_MODEL_INPUT_COUNT;
        logits = (int8_t *)malloc(sample_count * VOICE_MODEL_CLASS_COUNT);
        if (logits == NULL)
        {
            free(input);
            return 2;
        }

        for (i = 0U; i < sample_count; ++i)
        {
            if (voice_kws_run(&g_kws, (const int8_t *)input + (i * VOICE_MODEL_INPUT_COUNT)) != 0)
            {
                fprintf(stderr, "inference failed at sample %u\n", (unsigned)i);
                free(input);
                free(logits);
                return 3;
            }
            memcpy(logits + (i * VOICE_MODEL_CLASS_COUNT), g_kws.logits,
                   VOICE_MODEL_CLASS_COUNT);
        }

        out = fopen(argv[2], "wb");
        if (out == NULL)
        {
            fprintf(stderr, "cannot write %s\n", argv[2]);
            free(input);
            free(logits);
            return 2;
        }
        fwrite(logits, 1U, sample_count * VOICE_MODEL_CLASS_COUNT, out);
        fclose(out);

        printf("INFERRED %u\n", (unsigned)sample_count);
        free(input);
        free(logits);
    }

    puts("C voice kws tests passed");
    return 0;
}
