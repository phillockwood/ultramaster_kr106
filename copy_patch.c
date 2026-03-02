/**
 * Copyright (c) UltraMaster Group, LLC. All Rights Reserved.
 * $Revision: 1.1 $$Date: 2000/02/22 20:12:54 $
 */
#include "kr106_patch.h"
#include <stdio.h>
#include <errno.h>
#include <stdlib.h>

int
main( int argc, char** argv )
{
    char* srcFile;
    int srcNo;
    char* destFile;
    int destNo;

    kr106_patch* srcPatches;
    kr106_patch* destPatches;

    if ( argc < 4 )
    {
	fprintf( stderr, "Usage: %s srcFile srcNo destFile destNo\n", argv[0] );
	exit(1);
    }

    srcFile  = argv[1];
    srcNo    = atoi(argv[2]);
    destFile = argv[3];
    destNo   = atoi(argv[4]);

    srcPatches  = kr106_patchset_new();
    destPatches = kr106_patchset_new();

    if ( load_patches( srcFile, srcPatches ) < 0 )
    {
	exit(1);
    }

    if ( load_patches( destFile, destPatches ) < 0 )
    {
	exit(1);
    }

    destPatches[ destNo ] = srcPatches[ srcNo ];

    save_patches( destFile, destPatches );

    kr106_patchset_delete( srcPatches );
    kr106_patchset_delete( destPatches );

    return( 0 );
}
