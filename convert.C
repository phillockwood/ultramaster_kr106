/**
 * Copyright (c) UltraMaster Group, LLC. All Rights Reserved.
 * $Revision: 1.2 $$Date: 2000/03/17 16:14:02 $
 */
#include <stdio.h>
#include "kr106_patch.h"

int
main( int argc, char** argv )
{
    int lfo_rate;
    int lfo_dly;
    int dco_lfo;
    int dco_pwm;
    int noise;
    int vcf_frq;
    int vcf_res;
    int vcf_env;
    int vcf_lfo;
    int vcf_kbyd;
    int vca_level;
    int a;
    int d;
    int s;
    int r;
    int sub;

    int seventeen;
    int eighteen;

    char name[64];

    kr106_patch* patchset = kr106_patchset_new();

    FILE* file = fopen( argv[1], "r" );
    char buff[ BUFSIZ ];

    int i = 0;
    while( i < 100 && fgets( buff, BUFSIZ, file ) != NULL )
    {
	sscanf( buff, "%x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x,%[^\n]",
		&lfo_rate,
		&lfo_dly,
		&dco_lfo,
		&dco_pwm,
		&noise,
		&vcf_frq,
		&vcf_res,
		&vcf_env,
		&vcf_lfo,
		&vcf_kbyd,
		&vca_level,
		&a,
		&d,
		&s,
		&r,
		&sub,
		&seventeen,
		&eighteen, name );
		
	kr106_patch* patch = &patchset[ i ];
	patch->used = 1;
	patch->name = name;
	if ( seventeen & 1 )
	    patch->octave_transpose = 0;
	else if ( seventeen & (1<<1) )
	    patch->octave_transpose = 2;
	else
	    patch->octave_transpose = 1;

	patch->volume = vca_level / 127.0;
	patch->lfo_rate = lfo_rate / 127.0;
	patch->lfo_delay = lfo_dly / 127.0;
	patch->dco_lfo = dco_lfo / 127.0;
	patch->dco_pwm = dco_pwm / 127.0;
	patch->dco_pwm_mod = (eighteen & 1) * 2;
	patch->dco_pulse_switch = (seventeen & (1<<3))!=0;
	patch->dco_saw_switch = (seventeen & (1<<4)) != 0;
	patch->dco_sub_switch = sub > 0;
	patch->dco_sub = sub / 127.0;
	patch->dco_noise = noise / 127.0;
	if ((eighteen & (1<<4 )) == 0 )
	{
	    if ((eighteen & (1<<3)) == 0)
		patch->hpf_frq = .75;
	    else
		patch->hpf_frq = .5;		
	}
	else
	{
	    if ((eighteen & (1<<3)) == 0)
		patch->hpf_frq = .25;
	    else
		patch->hpf_frq = 0;

	}

	patch->vcf_frq = vcf_frq / 127.0;
	patch->vcf_res = vcf_res / 127.0;
	patch->vcf_env_invert = eighteen & (1<<2) != 0;
	patch->vcf_env = vcf_env / 127.0;
	patch->vcf_lfo = vcf_lfo / 127.0;
	patch->vcf_kbd = vcf_kbyd / 127.0;
	patch->vca_mode = (eighteen & (1<<1)) != 0;
	patch->env_attack = a / 127.0;
	patch->env_decay = d / 127.0;
	patch->env_sustain = s / 127.0;
	patch->env_release = r / 127.0;
	patch->chorus_I_switch = ((seventeen & (1<<5))==0 && (seventeen & (1<<6))!=0);
	patch->chorus_II_switch =((seventeen & (1<<5))==0 && (seventeen & (1<<6))==0);

	i++;
    }

    save_patches( "kr106presets", patchset );
}




