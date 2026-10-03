#ifndef SMART_HAND_TESTS_STUBS_RTDEVICE_H
#define SMART_HAND_TESTS_STUBS_RTDEVICE_H

/*
 * Host stub for the RT-Thread device header.
 *
 * voice_audio_titan.c includes it, but the PDM path deliberately does not go
 * through the device framework: R_PDM_Read returns FSP_ERR_UNSUPPORTED, so
 * capture can only be driven from the data interrupt. Nothing from this header
 * is used, and it stays empty on purpose -- the tests assert that no device
 * indirection sneaks into the audio path.
 */

#include <rtthread.h>

#endif
