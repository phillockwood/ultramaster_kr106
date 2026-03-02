/**
 * Copyright (c) UltraMaster Group, LLC. All Rights Reserved.
 * $Revision: 1.1 $$Date: 2000/02/22 20:12:54 $
 */
#include "kr106_patch.h"
#include <stdio.h>
#include <errno.h>

int
main( int argc, char** argv )
{
    int i;
    kr106_patch* patches;

    if ( argc < 2 )
    {
	fprintf( stderr, "Usage: %s patchfile\n", argv[0] );
	exit(1);
    }

    patches = kr106_patchset_new();
    if ( load_patches( argv[1], patches ) < 0 )
    {
	exit(1);
    }
    
    for( i = 0; i < NUM_PATCHES; i++ )
    {
	printf( "%02d %s\t", i, patches[ i ].used ? "used" : "free" );
	if ( i % 10 == 10 )
	    printf( "\n" );
    }

    kr106_patchset_delete( patches );

    return( 0 );
}
