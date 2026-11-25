# PAD-1576: a card write and a card backup leave the free blocks alone

David asked for ten ideas to make the slow parts of the app faster, then:
"Do your recommendation". The recommendation was ideas 1 and 5 together,
since they share one reader.

## What was slow

- **Writing a card** (`flash_image_to_device`) wrote every byte of the image
  and then read every byte back to verify it, free space included.
- **Backing a card up** (`read_device_to_image`) read every sector of the
  card.

Across the 56 newest Spike 2 builds in the library, 286 of 552 GB is in use:
**52%**. The rest is blocks the filesystems themselves call free.

| image | size | in use |
|---|---|---|
| James Bond 60th LE 1.11 (8G) | 7.32 GB | 1.45 GB |
| Iron Maiden Pro 1.18 (8G) | 7.32 GB | 2.60 GB |
| King Kong Pro 1.01 (16G) | 14.43 GB | 4.65 GB |
| Aerosmith 1.16 (8G) | 7.32 GB | 5.59 GB |
| Godzilla Pro 1.16 (8G) | 7.32 GB | 6.24 GB |
| Metallica 1.05 (32G) | 28.27 GB | 11.24 GB |
| Rush Pro 1.19 (16G) | 14.43 GB | 11.04 GB |

A card write is the write plus the verify, so both passes shrink by the same
share. The time saved on a real card is that share of the old time; the
card's own speed does not change.

## What changed

- `core/ext4_used.py`: `fs_used_ranges` reads an ext2/3/4 filesystem's
  superblock, group descriptors and block bitmaps and answers the byte
  ranges in use. Pure Python; about 0.1 s for a 16 GB image.
- `rawdevice.copy_ranges`: walks the partition table and the EBR chain, asks
  `fs_used_ranges` about every Linux partition, and answers what to copy:
  everything except the provably free blocks. Ranges are sector aligned and
  stretches closer than 1 MiB are joined.
- `copy_image_onto` and `_verify_flash_readback` take those ranges; the
  flash writes and verifies only them. `read_device_to_image` reads only
  them into a sparse image of the card's full size (`sparse_truncate`, as
  the menu-only read already did).

## Unknown means copy

A partition is copied whole unless all of this holds:

- it has an ext superblock with sane geometry that fits the partition;
- the filesystem is clean and its journal needs no replay (a journal waiting
  to be replayed can carry a newer bitmap than the one on disk). The data
  partition of a card pulled from a running machine is in this state, so a
  backup reads it whole;
- no feature that changes what a bitmap bit means (bigalloc, meta_bg) and no
  feature bit the code does not know;
- every group's bitmap agrees with the free count in its own descriptor.

Everything outside a Linux partition is always copied: the partition table,
the EBR sectors, the gaps, the FAT boot partition. A card with no MBR is one
range. The "keep the card's settings" overlay is always written in full.
The CGC installer images' filesystems do not pass the checks today and are
copied whole, as before.

`PAD_COPY_ALL_BLOCKS=1` (or `skip_free=False`) is the old way.

## What a card written this way is

Not byte-identical to the image: the free blocks keep what the card held.
Every block any file, directory or table uses is the image's, and is
verified. The log says "every block in use matches the image" rather than
"byte-for-byte" when blocks were skipped.

## How it was proven

- `tests/test_copy_used_blocks.py`: hand-built filesystems (32 and 64 byte
  descriptors, uninitialised groups, every refusal), a card image with a
  primary and a logical partition, a flash onto a card full of 0xA5 (free
  blocks still 0xA5, used ones the image's, verify catches a flipped used
  byte), and a backup (holes read as zero).
- Real image (Aerosmith 1.16, 8G) written by the app's own
  `flash_image_to_device` onto a 7.86 GB file filled with 0xA5, then backed
  up with `read_device_to_image`. Judged by e2fsprogs, not by the new
  reader: `e2fsck -fn` of every partition, and a byte compare against the
  image in which every difference must lie inside a block `dumpe2fs` lists
  as free. Results in the ticket.
- The backup image: 7,861,174,272 bytes long, 6,000,017,408 on disk.

No physical card was written for this ticket.
