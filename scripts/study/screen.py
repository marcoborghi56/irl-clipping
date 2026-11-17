import cv2, numpy as np, sys
from pathlib import Path
for cdir in sorted(Path("set").iterdir()):
    rows=[]
    for p in sorted(cdir.glob("*.mp4")):
        cap=cv2.VideoCapture(str(p)); n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fr=[]
        for k in range(6):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n*(k+0.5)/6)); ok,f=cap.read()
            if not ok: f=np.zeros((10,10,3),np.uint8)
            h=160; f=cv2.resize(f,(int(f.shape[1]*h/f.shape[0]),h)); fr.append(cv2.copyMakeBorder(f,0,0,0,4,cv2.BORDER_CONSTANT))
        strip=np.hstack(fr); lab=np.zeros((160,230,3),np.uint8)
        name=p.stem.split("_")
        cv2.putText(lab,name[0],(6,40),cv2.FONT_HERSHEY_SIMPLEX,0.9,(255,255,255),2); cv2.putText(lab,name[1],(6,80),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,220,255),2)
        cv2.putText(lab,"_".join(name[2:]),(6,120),cv2.FONT_HERSHEY_SIMPLEX,0.5,(200,200,200),1)
        rows.append(np.hstack([lab,strip]))
    W=max(r.shape[1] for r in rows); rows=[cv2.copyMakeBorder(r,0,4,0,W-r.shape[1],cv2.BORDER_CONSTANT) for r in rows]
    out=f"screen_{cdir.name}.jpg"; cv2.imwrite(out,np.vstack(rows),[cv2.IMWRITE_JPEG_QUALITY,70]); print(out)
