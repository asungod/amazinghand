#ifndef TITAN_TRUST_MODEL_H
#define TITAN_TRUST_MODEL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TITAN_TRUST_FEATURE_COUNT 10
#define TITAN_TRUST_CLASS_COUNT 3

typedef enum
{
    TITAN_TRUST_TRUSTED = 0,
    TITAN_TRUST_UNCERTAIN = 1,
    TITAN_TRUST_ANOMALOUS = 2
} titan_trust_class_t;

/*
 * Advisory inference only. It never authorizes motion.
 * Invalid/non-finite input fails closed to TITAN_TRUST_ANOMALOUS.
 */
titan_trust_class_t titan_trust_predict(
    const float features[TITAN_TRUST_FEATURE_COUNT],
    float logits[TITAN_TRUST_CLASS_COUNT]);

const char *titan_trust_class_name(titan_trust_class_t value);

#ifdef __cplusplus
}
#endif

#endif
