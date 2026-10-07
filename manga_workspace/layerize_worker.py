"""Standalone, CPU-only layerization worker. Never imports Krita or mutates source documents."""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL']='2'
os.environ['CUDA_VISIBLE_DEVICES']='-1'
import argparse, hashlib, io, json, zipfile, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
from pathlib import Path
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from PIL import Image, ImageDraw
from detector_worker import detect


def progress(value, message):
    print(json.dumps({'progress':value,'message':message},ensure_ascii=False),flush=True)


def rect(box, pad=0):
    x, y, w, h = box
    result = np.zeros((H, W), np.uint8)
    result[max(0,y-pad):min(H,y+h+pad), max(0,x-pad):min(W,x+w+pad)] = 1
    return result


def png(array):
    output = io.BytesIO()
    Image.fromarray(array).save(output, 'PNG')
    return output.getvalue()


def rgba(mask):
    return np.dstack((original[:,:,:3] * mask[:,:,None], original[:,:,3] * mask))


def character_mask(box, panel):
    x,y,w,h = box
    pad = 24
    x0,y0,x1,y1=max(0,x-pad),max(0,y-pad),min(W,x+w+pad),min(H,y+h+pad)
    crop = rgb[y0:y1,x0:x1]
    scale = min(1, 650/max(crop.shape[:2]))
    small = cv2.resize(crop, None, fx=scale, fy=scale)
    bounds=(round((x-x0)*scale),round((y-y0)*scale),max(2,round(w*scale)),max(2,round(h*scale)))
    bounds=(bounds[0],bounds[1], min(bounds[2],small.shape[1]-bounds[0]-1),min(bounds[3],small.shape[0]-bounds[1]-1))
    labels=np.zeros(small.shape[:2],np.uint8)
    try:
        cv2.grabCut(small, labels, bounds, np.zeros((1,65)),np.zeros((1,65)),5,cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return rect(box)&panel
    cut=np.isin(labels,[cv2.GC_FGD,cv2.GC_PR_FGD]).astype(np.uint8)
    cut=cv2.resize(cut,(x1-x0,y1-y0),interpolation=cv2.INTER_NEAREST)
    result=np.zeros((H,W),np.uint8)
    result[y0:y1,x0:x1]=cut
    return result & panel


def bubble_mask(box, panel):
    white=((rgb.min(axis=2)>240)&(np.ptp(rgb,axis=2)<14)).astype(np.uint8)&panel
    white=cv2.morphologyEx(white,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))&panel
    n,labels,stats,_=cv2.connectedComponentsWithStats(white)
    target=rect(box).astype(bool)
    best=max(range(1,n),key=lambda i: np.count_nonzero((labels==i)&target),default=0)
    if not best or np.count_nonzero((labels==best)&target)<target.sum()*.35:
        return np.zeros((H,W),np.uint8)
    if stats[best,cv2.CC_STAT_AREA]>panel.sum()*.45:
        return np.zeros((H,W),np.uint8)
    component=(labels==best).astype(np.uint8)
    contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    fill=np.zeros_like(component)
    cv2.drawContours(fill,contours,-1,1,-1)
    return cv2.dilate(fill,np.ones((5,5),np.uint8))&panel


def build(refined):
    groups=[]
    used=np.zeros((H,W),np.uint8)
    reviews=[]
    for number, frame in enumerate(frames,1):
        progress(25 + round(55*(number-1)/len(frames)), f'コマ{number}/{len(frames)}を分離中')
        panel=rect(frame['bbox']) & (1-used)
        used |= panel
        frame_mask=panel & (1-cv2.erode(panel,np.ones((9,9),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0))
        occupied=frame_mask.copy()
        categories={'テキスト':[], '吹き出し':[], 'キャラ':[], '背景':[]}
        x,y,w,h=frame['bbox']
        items=[d for d in data['detections'] if d['kind']!='frame'
               and x<=d['bbox'][0]+d['bbox'][2]/2<x+w and y<=d['bbox'][1]+d['bbox'][3]/2<y+h]
        texts=[d for d in items if d['kind']=='text' and d['score'] >= .7]
        bubbles=[]
        for i,item in enumerate(texts,1):
            region=rect(item['bbox'],3)&panel
            bubble=matched_bubble(item['bbox'],panel)
            if bubble.any():
                dark=(rgb.min(axis=2)<190).astype(np.uint8)&region
                mask=cv2.dilate(dark,np.ones((3,3),np.uint8))&region
                bubbles.append((f'吹き出し{i:02}',bubble))
                title=f'セリフ{i:02}（画像）'
            else:
                mask=region
                title=f'文字{i:02}（画像・範囲要確認）'
                reviews.append(f'コマ{number:02}: 吹き出し外の文字は矩形保持。絵本の印刷文字・縁取り文字を要確認。')
            mask &= 1-occupied
            occupied |= mask
            categories['テキスト'].append((title,mask))
        for name,mask in bubbles:
            mask &= 1-occupied
            occupied |= mask
            categories['吹き出し'].append((name,mask))
        people=sorted([d for d in items if d['kind']=='character'],key=lambda d:d['bbox'][2]*d['bbox'][3])
        for i,item in enumerate(people,1):
            mask=character_mask(item['bbox'],panel) if refined else rect(item['bbox'])&panel
            mask &= 1-occupied
            occupied |= mask
            categories['キャラ'].append((f'人物{i:02}（要確認）',mask))
        categories['背景'].append(('背景（見えている部分・補完なし）',panel&(1-occupied)))
        groups.append((f'コマ{number:02}',frame_mask,categories))
    return groups,1-used,reviews


def export(name,groups,outside):
    root=ET.Element('image',w=str(W),h=str(H),name=name,version='0.0.3')
    stack=ET.SubElement(root,'stack')
    coverage=np.zeros((H,W),np.uint16)
    count=0
    with zipfile.ZipFile(ROOT/(name+'.ora'),'w') as z:
        z.writestr('mimetype','image/openraster',compress_type=zipfile.ZIP_STORED)
        def layer(parent,title,mask,visible=True):
            nonlocal count
            count+=1
            path=f'data/layer{count:03}.png'
            ys,xs=np.nonzero(mask)
            x0,y0,x1,y1=(int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1) if len(xs) else (0,0,1,1)
            z.writestr(path,png(rgba(mask)[y0:y1,x0:x1]),compress_type=zipfile.ZIP_DEFLATED)
            ET.SubElement(parent,'layer',name=title,src=path,x=str(x0),y=str(y0),opacity='1.0',visibility='visible' if visible else 'hidden',**{'composite-op':'svg:src-over'})
            if visible:
                coverage[:]+=mask
        for title,border,categories in groups:
            group=ET.SubElement(stack,'stack',name=title,opacity='1.0',visibility='visible',**{'composite-op':'svg:src-over'})
            layer(group,'コマ枠（元画像）',border)
            for category,items in categories.items():
                folder=ET.SubElement(group,'stack',name=category,opacity='1.0',visibility='visible',**{'composite-op':'svg:src-over'})
                for title,mask in items:
                    layer(folder,title,mask)
        layer(stack,'紙・コマ外',outside)
        layer(stack,'元画像（非表示・保存用）',np.ones((H,W),np.uint8),False)
        z.writestr('stack.xml',ET.tostring(root,encoding='utf-8',xml_declaration=True))
        z.writestr('mergedimage.png',png(original))
        thumb=Image.fromarray(original);thumb.thumbnail((256,256));buf=io.BytesIO();thumb.save(buf,'PNG');z.writestr('Thumbnails/thumbnail.png',buf.getvalue())
    assert np.all(coverage==1), 'Pixel loss or duplicate ownership'
    return count



def load_bubbles(weights):
    import h5py
    import tf_keras
    import tensorflow as tf
    expected='8d3f3aaa5bdfae324d6f27fe7c49c15cd0905a1bda0332a4995983070caa5249'
    if hashlib.sha256(weights.read_bytes()).hexdigest()!=expected:
        raise ValueError('吹き出しモデルの照合に失敗しました')
    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    with h5py.File(weights,'r') as file:
        model=tf_keras.models.load_model(file,compile=False,safe_mode=True)
    h,w=model.input_shape[1:3]
    tensor=np.array(Image.fromarray(rgb).resize((w,h)).convert('L'),dtype=np.float32)[None,:,:,None]/255
    prediction=model(tensor,training=False).numpy()[0]
    mask=cv2.resize((np.argmin(prediction,axis=-1)==1).astype(np.uint8),(W,H),interpolation=cv2.INTER_NEAREST)
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    result=[]
    for x,y,w,h,area in stats[1:]:
        if area<max(80,W*H*.001):continue
        for frame in frames:
            fx,fy,fw,fh=frame['bbox']
            if fx<=x+w/2<fx+fw and fy<=y+h/2<fy+fh:
                candidate=bubble_mask([int(x),int(y),int(w),int(h)],rect(frame['bbox']))
                if candidate.any():result.append(candidate)
                break
    return result


def matched_bubble(box,panel):
    target=rect(box)
    for mask in bubbles:
        if np.count_nonzero(mask&target)>target.sum()*.5:
            return mask&panel
    return np.zeros((H,W),np.uint8)


def run(args):
    global ROOT,original,rgb,W,H,data,frames,bubbles
    ROOT=Path(args.output)
    ROOT.mkdir(parents=True,exist_ok=True)
    original=np.array(Image.open(args.image).convert('RGBA'))
    H,W=original.shape[:2]
    if W*H>12000000:
        raise ValueError('試験版は1200万画素までです。複製した画像を縮小して実行してください')
    alpha=original[:,:,3:4].astype(np.float32)/255
    rgb=(original[:,:,:3]*alpha+255*(1-alpha)).astype(np.uint8)
    cv2.setNumThreads(4);cv2.setRNGSeed(0)
    progress(5,'コマ・人物・文字を検出中')
    data=detect(args.image,args.detector)
    raw_frames=[d for d in data['detections'] if d['kind']=='frame']
    frames=[]
    for candidate in sorted(raw_frames,key=lambda d:-d['score']):
        candidate_mask=rect(candidate['bbox'])
        if not any(np.count_nonzero(candidate_mask&rect(f['bbox']))/max(1,min(candidate_mask.sum(),rect(f['bbox']).sum()))>.9 for f in frames):
            frames.append(candidate)
    if not frames:frames=[{'bbox':[0,0,W,H],'score':0}]
    # Group rows by relative vertical overlap, then right-to-left within a row.
    frames.sort(key=lambda d:(round(d['bbox'][1]/max(1,H*.04)),-d['bbox'][0]))
    progress(15,'文字候補から吹き出しを解析中')
    bubbles=load_bubbles(Path(args.bubble))
    groups,outside,reviews=build(not args.rectangles)
    progress(85,'レイヤー原稿を保存中')
    count=export('layerized',groups,outside)
    overlay=rgb.copy()
    people=np.zeros((H,W),np.uint8)
    bubble_union=np.zeros((H,W),np.uint8)
    for _,_,categories in groups:
        for _,mask in categories['キャラ']:people |= mask
        for _,mask in categories['吹き出し']:bubble_union |= mask
    overlay[people>0]=(overlay[people>0]*.6+np.array([255,90,20])*.4).astype(np.uint8)
    overlay[bubble_union>0]=(overlay[bubble_union>0]*.6+np.array([0,210,100])*.4).astype(np.uint8)
    im=Image.fromarray(overlay);im.thumbnail((900,1000));im.save(ROOT/'preview.png')
    # Re-read actual exported layers and validate the visible composite.
    with zipfile.ZipFile(ROOT/'layerized.ora') as z:
        image=Image.new('RGBA',(W,H))
        def compose(node):
            for child in reversed(list(node)):
                if child.get('visibility')=='hidden':continue
                if child.tag=='stack':compose(child)
                else:image.alpha_composite(Image.open(io.BytesIO(z.read(child.get('src')))).convert('RGBA'),(int(child.get('x')),int(child.get('y'))))
        compose(ET.fromstring(z.read('stack.xml')).find('stack'))
        result=np.array(image)
        visible=original[:,:,3]>0
        if not np.array_equal(result[visible],original[visible]) or not np.array_equal(result[:,:,3],original[:,:,3]):
            raise ValueError('再合成が元画像と一致しないため適用を停止しました')
    manifest={'panels':len(frames),'layers':count,'characters':sum(len(c['キャラ']) for _,_,c in groups),
              'bubbles':sum(len(c['吹き出し']) for _,_,c in groups),'reviews':reviews,
              'method':'rectangles' if args.rectangles else 'GrabCut (experimental)',
              'verified_composite':True}
    (ROOT/'result.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    progress(100,'結果を確認してください')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--image',required=True)
    parser.add_argument('--detector',required=True)
    parser.add_argument('--bubble',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--rectangles',action='store_true')
    run(parser.parse_args())
