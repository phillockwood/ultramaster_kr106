/**
 * Copyright (c) UltraMaster Group, LLC. All Rights Reserved.
 * $Revision: 1.8 $$Date: 2000/03/09 18:52:09 $
 */
#ifndef KR106_PATCH_H
#define KR106_PATCH_H

#define KR106_PATCH_FILE_MAGIC 0xafabceee
#define KR106_PATCH_FILE_VERSION 2
#define NUM_PATCHES 100

/* in future versions the 'unused' may be turned into something :-) */
typedef struct
{
    int magic;
    int version;
    char unused[4096 - 2 * sizeof(int)];
} kr106_patch_file_header;

typedef struct 
{
    int    used;
    double bender_dco;
    double bender_vcf;
    double lfo_trigger;
    double volume;
    double octave_transpose;
    double arpeggio_switch;
    double arpeggio_mode;
    double arpeggio_range;
    double arpeggio_rate;
    double lfo_rate;
    double lfo_delay;
    double lfo_mode;
    double dco_lfo;
    double dco_pwm;
    double dco_pwm_mod;
    double dco_pulse_switch;
    double dco_saw_switch;
    double dco_sub_switch;
    double dco_sub;
    double dco_noise;
    double hpf_frq;
    double vcf_frq;
    double vcf_res;
    double vcf_env_invert;
    double vcf_env;
    double vcf_lfo;
    double vcf_kbd;
    double vca_mode;
    double env_attack;
    double env_decay;
    double env_sustain;
    double env_release;
    double chorus_I_switch;
    double chorus_II_switch;
    char   name[64];
} kr106_patch;

#ifdef __cplusplus
extern "C"
{
#endif
kr106_patch* kr106_patchset_new();
void kr106_patchset_delete();
int save_patches( const char *filename, kr106_patch* patches );
int load_patches( const char *filename, kr106_patch* patches );
#ifdef __cplusplus
}
#endif
#endif /* KR106_PATCH_H */



