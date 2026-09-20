# Fix loop

## 1. Worst gate

Wall lengths on the depth tier (ARCore, TECNO LI9), bedroom capture
`20260920-035737-0c6f2b`, tape ground truth 426.7 x 365.8 cm.

| | measured | error |
|---|---|---|
| length | 393.0 cm | -7.9 percent |
| width | 314.0 cm | -14.2 percent |

Gate for this tier is the LiDAR gate, 1 percent per wall (repeatability row) and
the plan gates. This is the largest failing number in the benchmark, and it is
systematic: both dimensions short, both captures of the room short.

## 2. Root cause hypothesis and evidence

ARCore's smooth depth fills textureless wall regions with values biased toward
the camera. The fitted wall line (RANSAC, then Manhattan snap) sits at the
centre of a point band that is 30 to 66 cm thick and lies almost entirely on
the room side of the true wall. The true wall face is near the outer edge of
that band.

Evidence, measured on the capture (signed distance of every point in each
wall's band along the outward normal, positive = beyond the fitted line):

| wall | band spread p10..p90 | outward p80 of band | outward p90 |
|---|---|---|---|
| x- | 32 cm | +8.8 cm | +14 cm |
| x+ | 50 cm | +19.2 cm | +27 cm |
| z- | 66 cm | +37.7 cm | +47 cm |
| z+ | 50 cm | +20.7 cm | +31 cm |

The sums of the outward p80 offsets per axis, 28 cm and 58 cm, are the exact
amounts by which the two dimensions are short (34 cm and 52 cm), within the
band noise. The LiDAR sample scans show band spreads of 3 to 8 cm, so the same
bias does not exist there, which is consistent with the hypothesis that it is
a depth-from-motion artefact and not a fitting bug.

## 3. Fix and prediction

Fix: `plane_extraction.refine_wall_faces`. When a wall's inlier band is thicker
than 15 cm, move the wall line outward to the 80th percentile of the outward
distance of all points in the band. Thin bands are left where RANSAC put them.
Switch: `scripts/floorplan.py --wall-face centre|outer`, default `outer`.

Prediction before running: both bedroom dimensions within 3 percent, LiDAR
sample rooms unchanged.

## 4. Result

| | before (`--wall-face centre`) | after (`--wall-face outer`) | truth |
|---|---|---|---|
| length | 393.0 (-7.9 percent) | 421.0 (-1.3 percent) | 426.7 |
| width | 314.0 (-14.2 percent) | 372.4 (+1.8 percent) | 365.8 |
| area | 12.34 m2 | 15.68 m2 | 15.61 m2 |
| LiDAR sample shifts | n/a | all zero (bands under 15 cm) | |

Prediction held on the original fix-loop capture. The gate itself (1 percent)
is still not met: the residual sits in the choice of percentile, which was set
from this one capture. A later closed bedroom capture
(`20260920-135411-18977b`) measures +2.8 percent and +1.5 percent on the depth
tier, so the held-out check fails the 1 percent wall gate even though it is far
better than the pre-fix -7.9 and -14.2 percent case. Sparse captures still do
not close a polygon and remain unscored.

## 5. Regenerate

```
for face in centre outer; do
  mkdir -p data/fixloop/$face
  cp data/captures/20260920-035737-0c6f2b/capture.json data/fixloop/$face/
  uv run python scripts/floorplan.py data/fixloop/$face --wall-face $face
done
```

Web captures are processed in place, so the copy keeps the two runs apart.

Diff: the commit "Outer wall face for thick depth bands (fix loop)", files
`src/floorplan_takehome/plane_extraction.py` (`refine_wall_faces`),
`src/floorplan_takehome/pipeline.py` (switch and diagnostics), `scripts/floorplan.py`.
