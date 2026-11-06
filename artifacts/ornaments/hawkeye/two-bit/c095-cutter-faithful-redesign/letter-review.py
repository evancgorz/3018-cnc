"""Offline typography study: replace raster lettering and model V-bit cuts.

This is a design preview, not a CNC program or a change to the active job.
"""
from pathlib import Path
import importlib.util, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('prep',HERE/'prepare.py')
prep=importlib.util.module_from_spec(spec); spec.loader.exec_module(prep)
S=20
size=110*S
mask=Image.new('L',(size,size),0)
font=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',round(6.0*S))

def curved(text, center_angle, spread, radius, bottom=False):
    # Individual character widths inform angular spacing while preserving an
    # upright baseline along the lower arc.
    widths=[font.getlength(c) for c in text]
    total=sum(widths); cursor=0
    for char,width in zip(text,widths):
        fraction=(cursor+width/2)/total-.5
        angle=center_angle + (-1 if not bottom else 1)*spread*fraction
        cursor+=width
        if char==' ': continue
        tile=Image.new('L',(S*10,S*10),0)
        ImageDraw.Draw(tile).text((S*5,S*5),char,font=font,fill=255,anchor='mm')
        # Top text tilts toward its radial direction; lower text stays upright.
        rotation=angle-90 if not bottom else angle-270
        tile=tile.rotate(rotation,resample=Image.Resampling.BICUBIC)
        a=math.radians(angle)
        x=(55+radius*math.cos(a))*S; y=(110-(55+radius*math.sin(a)))*S
        mask.paste(ImageChops.lighter(mask.crop((int(x)-S*5,int(y)-S*5,int(x)+S*5,int(y)+S*5)),tile),(int(x)-S*5,int(y)-S*5))

from PIL import ImageChops
curved('DOME RIDERS',90,98,39.2)
curved('VAW-120 Key West',270,111,39.2,True)
mask.save(HERE/'clean-letter-mask.png')

depth=np.load(HERE/'modeled-removal-depth-mm.npy')
n=depth.shape[0]; c=(np.arange(n)+.5)*prep.GRID
x=c[None,:]-55; y=c[:,None]-55
radius=np.hypot(x,y); angle=np.degrees(np.arctan2(y,x))%360
erase=(radius>32.2)&(radius<42.4)&(((angle>35)&(angle<145))|((angle>215)&(angle<325)))
depth[erase]=0
# Erode to keep the entire cutter footprint within the letter shapes.
# 0.6 mm deep produces a 0.422 mm top diameter.  At 40 px/mm the
# conservative 19-pixel erosion approximates its 0.211 mm radius.
inset=mask.filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.MinFilter(15))
arr=np.asarray(inset)>127
paths=[]
for row in range(0,size,3):
    line=arr[row]; edges=np.diff(np.r_[False,line,False].astype(np.int8))
    starts=np.flatnonzero(edges==1); ends=np.flatnonzero(edges==-1)
    yy=110-(row+.5)/S
    for a,b in zip(starts,ends):
        if b-a>=2: paths.append((((a+.5)/S,yy),((b-.5)/S,yy)))
prep.remove_surface(depth,paths,1.0)
prep.render(depth,'clean-letter-cutter-preview.png',shaded=True)
print(f'Created review preview using {len(paths)} letter strokes at Z -1.0 mm; not a CNC program.')
