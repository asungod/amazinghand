#include "titan_trust_model.h"

#include <math.h>
#include <stddef.h>

#define TITAN_TRUST_HIDDEN_COUNT 12

static const float g_feature_min[10] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
static const float g_feature_max[10] = {100.0f, 100.0f, 100.0f, 2000.0f, 1000.0f, 20.0f, 20.0f, 20.0f, 2000.0f, 100.0f};
static const float g_hidden_weights[10][12] = {
    {0.720399306f, 1.37634331f, 0.180194381f, -0.0899109991f, -2.25529627f, 1.39891478f, -1.95360891f, -0.0310982362f, -1.58284919f, -1.364263f, -3.12150047f, 1.92799626f},
    {0.154164017f, -0.518160709f, 0.520852894f, 0.113781093f, 1.12202719f, -1.27857311f, 2.53967325f, 0.0695441239f, -1.15533121f, 1.21099846f, 4.50143161f, -0.602432012f},
    {0.309339241f, 1.37599242f, 0.161274877f, -0.0928335339f, 1.61872622f, -4.57300139f, 2.56497827f, 0.263993367f, -0.0709765497f, 1.08007555f, 4.35458819f, -0.00117426272f},
    {-1.08097055f, -1.85970994f, -0.17592523f, 0.151000236f, 1.48413031f, -1.59155254f, 1.16846038f, -0.480250974f, 3.38020584f, -0.275643165f, 7.8077036f, 0.253195264f},
    {-0.409527986f, 1.08437173f, -0.256794153f, 0.306733739f, 3.09924156f, -2.33764462f, 2.40657121f, 0.353614395f, 3.52585786f, 1.64380523f, 3.03127531f, -3.01490865f},
    {0.936502891f, 2.2307772f, 0.392079163f, 0.277469831f, 0.220135731f, -2.07770406f, 3.04200236f, 0.375469807f, 0.486758575f, 2.20741539f, 4.04078321f, -1.36858866f},
    {1.26919613f, 2.20336859f, 0.00327979835f, 0.139302874f, -0.825659346f, 0.126936663f, 3.1367085f, 0.583538894f, -0.124890011f, 2.72494295f, 4.27341765f, -7.03441111f},
    {1.43083674f, 2.92401741f, 0.327115832f, 0.627945808f, 0.861969527f, -0.866111483f, 2.5279341f, 0.832057074f, 0.390099399f, 2.31956612f, -0.615971076f, -2.12304609f},
    {0.0730481007f, -0.479134793f, 0.237797736f, -0.199186492f, 1.42286354f, -3.98921645f, 2.70817338f, -0.130126329f, 2.41196767f, 1.12795175f, 8.57230898f, -1.85802955f},
    {0.771952715f, 2.13730378f, 0.185537699f, 0.275163092f, -2.62896453f, 3.38322216f, -2.36866724f, 0.446060892f, -2.44023393f, -0.58962814f, -7.03340094f, 0.27950269f}
};
static const float g_hidden_bias[12] = {-3.27572677f, -6.16817936f, -0.429678037f, -1.15788224f, 2.4507194f, -16.5385462f, -3.17344235f, -1.66020735f, 4.05816781f, -4.11832044f, 15.8365604f, -10.5742987f};
static const float g_output_weights[12][3] = {
    {0.139465647f, -0.26103328f, 0.444952919f},
    {-1.13482015f, -1.47574946f, 2.80134017f},
    {0.144179506f, 0.1971056f, 0.456371909f},
    {0.261968311f, -0.387391028f, 0.165117446f},
    {-1.47332384f, -1.15090667f, 2.58426034f},
    {17.41368f, -11.9006869f, -6.77562624f},
    {4.02638481f, -3.15445486f, -0.777837292f},
    {-0.728720297f, -0.714832345f, 0.783219531f},
    {-2.09516713f, -0.891821187f, 2.74710505f},
    {1.05166898f, -1.33397749f, -0.42989734f},
    {-6.77384774f, -4.72091472f, 11.2755613f},
    {7.05093967f, 6.8372709f, -14.0299951f}
};
static const float g_output_bias[3] = {-11.481247f, 2.38041376f, 8.63245173f};


static float clamp_value(float value, float minimum, float maximum)
{
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
}

titan_trust_class_t titan_trust_predict(
    const float features[TITAN_TRUST_FEATURE_COUNT],
    float logits[TITAN_TRUST_CLASS_COUNT])
{
    float normalized[TITAN_TRUST_FEATURE_COUNT];
    float hidden[TITAN_TRUST_HIDDEN_COUNT];
    float local_logits[TITAN_TRUST_CLASS_COUNT];
    size_t input_index;
    size_t hidden_index;
    size_t output_index;
    size_t best_index = TITAN_TRUST_ANOMALOUS;

    if (features == NULL)
    {
        return TITAN_TRUST_ANOMALOUS;
    }
    for (input_index = 0; input_index < TITAN_TRUST_FEATURE_COUNT; ++input_index)
    {
        float value = features[input_index];
        if (!isfinite(value))
        {
            return TITAN_TRUST_ANOMALOUS;
        }
        value = clamp_value(value, g_feature_min[input_index], g_feature_max[input_index]);
        normalized[input_index] =
            ((value - g_feature_min[input_index]) /
             (g_feature_max[input_index] - g_feature_min[input_index])) * 2.0f - 1.0f;
    }

    for (hidden_index = 0; hidden_index < TITAN_TRUST_HIDDEN_COUNT; ++hidden_index)
    {
        float value = g_hidden_bias[hidden_index];
        for (input_index = 0; input_index < TITAN_TRUST_FEATURE_COUNT; ++input_index)
        {
            value += normalized[input_index] * g_hidden_weights[input_index][hidden_index];
        }
        hidden[hidden_index] = value > 0.0f ? value : 0.0f;
    }

    for (output_index = 0; output_index < TITAN_TRUST_CLASS_COUNT; ++output_index)
    {
        float value = g_output_bias[output_index];
        for (hidden_index = 0; hidden_index < TITAN_TRUST_HIDDEN_COUNT; ++hidden_index)
        {
            value += hidden[hidden_index] * g_output_weights[hidden_index][output_index];
        }
        local_logits[output_index] = value;
        if (logits != NULL) logits[output_index] = value;
    }

    best_index = 0;
    for (output_index = 1; output_index < TITAN_TRUST_CLASS_COUNT; ++output_index)
    {
        if (local_logits[output_index] > local_logits[best_index])
        {
            best_index = output_index;
        }
    }
    return (titan_trust_class_t)best_index;
}

const char *titan_trust_class_name(titan_trust_class_t value)
{
    switch (value)
    {
    case TITAN_TRUST_TRUSTED: return "TRUSTED";
    case TITAN_TRUST_UNCERTAIN: return "UNCERTAIN";
    case TITAN_TRUST_ANOMALOUS: return "ANOMALOUS";
    default: return "UNKNOWN";
    }
}
