; TTC 3018 MVP air-cut test
; Set work X0/Y0 at the material origin and Z0 at the material surface.
; This file keeps the tool at least 3 mm above Z0 and never starts the spindle.
; Expected XY path: a 25 mm x 15 mm rectangle, starting at X5 Y5.

G21
G17
G90
G94
M5

G0 Z5
G0 X5 Y5
G1 Z3 F100
G1 X30 Y5 F300
G1 X30 Y20
G1 X5 Y20
G1 X5 Y5

G0 Z5
G0 X0 Y0
M5
M2
