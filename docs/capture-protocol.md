# Capture protocol (Route 2: stock apps)

One page. Follow it literally. Three tiers, pick the one you were asked for.
Every tier ends with a folder handed to the pipeline, one command per capture.

## What to install (once, under 5 minutes)

| tier | app | device | cost |
|---|---|---|---|
| LiDAR | Stray Scanner (App Store) | iPhone 12 Pro or newer Pro, iPad Pro | free |
| Video | built-in Camera app | iPhone 15 or newer | none |
| Photos | built-in Camera app | iPhone 15 or newer | none |
| Head-to-head | magicplan (App Store, Play Store) | same device | free tier |

Android phones with ARCore can also do the depth tier through the web capture
page served by the pipeline (Chrome, no install). That path is described in
docs/plan.md and is not part of this protocol.

## Before you start (all tiers)

- Turn on every light in the property. Open curtains. Do not use the flash.
- Close mirrored wardrobe doors where possible. Avoid pointing the camera at a
  mirror or a window for more than a moment.
- Clear the path you will walk. Do not move furniture during a capture.
- Hold the phone upright (portrait), two hands, at chest height.
- Move slowly: one step per second, turns over three seconds. Fast motion is the
  most common cause of a failed capture.

## LiDAR tier: Stray Scanner

1. Open Stray Scanner, tap the record button (red circle).
2. Stand in the doorway of the first room. Sweep the phone slowly across the
   room: left wall, back wall, right wall, then tilt down to the floor and up to
   the ceiling once each.
3. Walk the perimeter of the room about one metre from the walls, phone facing
   the wall you are walking along. Every wall must be seen from within two
   metres at least once.
4. Walk through the door into the next room and repeat steps 2 and 3. Do not stop
   the recording between rooms, one recording covers the whole property.
5. When every room and connecting hallway has been walked, stop the recording.
6. Budget 40 to 60 seconds per room plus 15 seconds per hallway.
7. Export: in Stray Scanner open the scan, tap Share, choose Save to Files. It
   writes a folder with `rgb.mp4`, `depth/`, `confidence/`, `odometry.csv`,
   `camera_matrix.csv`, `imu.csv`. Zip that folder.

Repeatability capture: record the same room a second time as a separate
recording, starting from the same doorway, same route.

## Video tier: Camera app

1. Camera app, Video, 1080p at 30 fps (Settings > Camera > Record Video). Lock
   the exposure by long-pressing the screen once you are in the room.
2. Same route as the LiDAR tier: doorway sweep including floor and ceiling,
   then the perimeter walk facing the walls, then through the door to the next
   room. One clip for the whole property, 40 to 60 seconds per room.
3. Do not zoom. Do not switch cameras. Do not pause.
4. Export the .mov or .mp4 file, original quality (AirDrop, or Files > Save).

## Photo tier: Camera app

1. Camera app, Photo, 1x lens, no zoom, no Live Photo, no portrait mode.
2. Per room, take 6 to 8 photos, standing at 6 to 8 points spread around the
   room, each photo aimed at the opposite wall so that the floor, the wall and
   the ceiling line are all in frame. Adjacent photos must overlap by at least
   half their width: take the next photo two steps sideways, not from the
   other side of the room.
3. Include the doorway to each neighbouring room in at least one photo, from
   inside the room.
4. Put each room's photos in its own folder named after the room
   (`bedroom/`, `kitchen/`, `hall/`). Original quality, HEIC or JPEG.

## Head-to-head: magicplan

1. magicplan, new project, add room, follow the app's corner-by-corner scan
   for each of the two benchmark rooms.
2. Export the plan as PDF and the project as JSON or CSV if the plan allows.
   Note the app version shown in Settings.

## Handing the files to the pipeline

Either open the pipeline's upload page on the phone and upload the zip or
folder, or copy it to the pipeline machine. Then:

```
uv run python scripts/floorplan.py <capture folder> <output folder>
```

The command detects the tier from the folder contents (Stray Scanner export,
video file, or per-room photo folders) and writes `plan.json`, `plan.png` and
`summary.json` to the output folder.

## What ruins a capture

- Walking backwards or spinning in place: no baseline, no geometry.
- A room done only from its doorway: far walls are noisy at every tier.
- Skipping the floor and ceiling tilt: no ceiling height.
- Recording in the dark or pointing at a lit window: depth holes, tracking loss.
- Stopping the recording between rooms: the rooms cannot be stitched.
