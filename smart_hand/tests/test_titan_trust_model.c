#include <math.h>
#include <stdio.h>

#include "titan_trust_model.h"

static int expect_class(const char *name,
                        const float features[TITAN_TRUST_FEATURE_COUNT],
                        titan_trust_class_t expected)
{
    float logits[TITAN_TRUST_CLASS_COUNT];
    titan_trust_class_t actual = titan_trust_predict(features, logits);
    if (actual != expected)
    {
        fprintf(stderr,
                "%s: expected %s got %s logits=%.3f,%.3f,%.3f\n",
                name,
                titan_trust_class_name(expected),
                titan_trust_class_name(actual),
                logits[0], logits[1], logits[2]);
        return 1;
    }
    return 0;
}

int main(void)
{
    const float trusted[TITAN_TRUST_FEATURE_COUNT] =
        {90, 4, 3, 500, 20, 0, 0, 0, 100, 98};
    const float uncertain[TITAN_TRUST_FEATURE_COUNT] =
        {68, 22, 18, 650, 140, 1, 0, 1, 500, 70};
    const float anomalous[TITAN_TRUST_FEATURE_COUNT] =
        {40, 55, 50, 1500, 500, 6, 5, 6, 1200, 25};
    float invalid[TITAN_TRUST_FEATURE_COUNT] =
        {90, 4, 3, 500, 20, 0, 0, 0, 100, 98};
    int failures = 0;

    failures += expect_class("trusted", trusted, TITAN_TRUST_TRUSTED);
    failures += expect_class("uncertain", uncertain, TITAN_TRUST_UNCERTAIN);
    failures += expect_class("anomalous", anomalous, TITAN_TRUST_ANOMALOUS);

    invalid[0] = NAN;
    failures += expect_class("non_finite_fail_closed",
                             invalid,
                             TITAN_TRUST_ANOMALOUS);
    if (titan_trust_predict(NULL, NULL) != TITAN_TRUST_ANOMALOUS)
    {
        fprintf(stderr, "NULL input did not fail closed\n");
        failures++;
    }

    if (failures != 0)
    {
        return 1;
    }
    puts("TITAN TRUST C MODEL TEST PASSED");
    return 0;
}

