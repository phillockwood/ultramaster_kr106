/**
 * Copyright (c) UltraMaster Group, LLC. All Rights Reserved.
 * $Revision: 1.9 $$Date: 2000/09/11 16:36:24 $
 */
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>

#ifndef _WIN32
#include <unistd.h>
#else
#include <io.h>
#endif

#include <util/sio.h>
#include <util/debug.h>

#include "kr106_patch.h"

static int load_version_1(int, kr106_patch *);
static int load_version_2(int, kr106_patch_file_header *, kr106_patch *);

void
init_patch( kr106_patch* patch )
{
    memset( patch, 0, sizeof( kr106_patch ) );
    strcpy( patch->name, "Untitled" );
    patch->octave_transpose = 2;
}

kr106_patch* kr106_patchset_new()
{
    int i;
    kr106_patch* retval = (kr106_patch*)malloc(NUM_PATCHES*sizeof(kr106_patch));
    for( i = 0; i < NUM_PATCHES; i++ )
    {
	init_patch(&retval[i]);
    }
    return( retval );
}

void kr106_patchset_delete( kr106_patch* patches )
{
    free( patches );
}

int save_patches(const char *filename, kr106_patch* patches)
{
    int fd;
    ssize_t nbytes;
    kr106_patch_file_header header;

    fd = open(filename, O_WRONLY|O_CREAT|O_TRUNC, 0666);
    if (fd < 0)
    {
	debug(DEBUG_SYSERROR, "can't open patch file %s for write", filename);
	return -1;
    }

    /* not endian compatible */
    header.magic = KR106_PATCH_FILE_MAGIC;
    header.version = KR106_PATCH_FILE_VERSION;
    memset(header.unused, 0, sizeof(header.unused));

    nbytes = sizeof(kr106_patch_file_header);
    if (writen(fd, &header, nbytes) != (int)nbytes)
    {
	debug(DEBUG_SYSERROR, "Short write writing patch file header %s", filename);
	debug(DEBUG_APPERROR, "If you exit now, your patches may be lost!");
	close(fd);
	return -1;
    }

    nbytes = sizeof(kr106_patch) * NUM_PATCHES;
    if (writen(fd, patches, nbytes) != nbytes)
    {
	debug(DEBUG_SYSERROR, "Short write on patch file %s", filename);
	debug(DEBUG_APPERROR, "If you exit now, your patches may be lost!");
	close(fd);
	return -1;
    }

    close(fd);
    return 0;
}

int load_patches(const char *filename, kr106_patch* patches)
{
    int fd;
    ssize_t nbytes;
    int i;
    int magic;
    int version;
    kr106_patch_file_header header;
    int retval = -1;

    fd = open(filename, O_RDONLY);
    if (fd < 0)
    {
	debug(DEBUG_SYSERROR, "can't open patch file %s for read", filename);
	goto out;
    }

    if (readn(fd, &magic, sizeof(int)) != sizeof(int))
    {
	debug(DEBUG_SYSERROR, "short read reading magic in %s", filename);
	goto out;
    }

    if (magic == KR106_PATCH_FILE_MAGIC)
    {
	header.magic = magic;

	/* we already read the magic */
	nbytes = sizeof(kr106_patch_file_header) - sizeof(int);
	if (readn(fd, &header.version, nbytes) != nbytes)
	{
	    debug(DEBUG_SYSERROR, "short read reading patch file header");
	    goto out;
	}
	version = header.version;
    }
    else if (magic == 1) /* old version 1 file format */
    {
	version = 1;
    }
    else
    {
	debug(DEBUG_APPERROR, "bad magic reading patch file %s", filename);
	goto out;
    }

    switch(version)
    {
    case 1:
	lseek(fd, 0, SEEK_SET);
	retval = load_version_1(fd, patches);
	break;
	
    case 2:
	retval = load_version_2(fd, &header, patches);
	break;
    default:
	debug(DEBUG_APPERROR, "unknown patch file version %d", version);
	goto out;
    }

    retval = 0;

 out:
    if (retval < 0)
    {
	debug(DEBUG_APPERROR, "failed to read patch file %s", filename);
	for( i = 0; i < NUM_PATCHES; i++ )
	    init_patch( &patches[i] );
    }

    if (fd >= 0)
	close(fd);

    return retval;
}

static int load_version_1(int fd, kr106_patch *patches)
{
    int i;
    ssize_t nbytes;

    debug(DEBUG_APPMSG1, "Reading and converting ver 1.0.1 patch file" );

    for( i = 0; i < NUM_PATCHES; i++ )
    {
	/* skip the int that holds version 1 on each patch */
	lseek(fd, sizeof(int), SEEK_CUR);

	/* new struct has 64 more bytes (for name) than old, 
	 * (once  we skip the 'version' using lseek above)
	 */
	nbytes = sizeof(kr106_patch) - 64;
	if (readn(fd, patches + i, nbytes) != nbytes)
	{
	    debug(DEBUG_SYSERROR, "short read reading patch %d", i);
	    return -1;
	}
    }

    return 0;
}

static int load_version_2(int fd, kr106_patch_file_header *header, kr106_patch *patches)
{
    ssize_t nbytes;

    nbytes = sizeof(kr106_patch) * NUM_PATCHES;
    if (readn(fd, patches, nbytes) != nbytes)
    {
	debug(DEBUG_SYSERROR, "short read on patch file");
	return -1;
    }

    return 0;
}
