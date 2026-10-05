"""Build the embedded, unlabelled diagram from TfL's published SVG.

Usage: python scripts/build-diagram.py /path/to/Standard-Tube-map.svg
Requires pymupdf. The game itself has no build or runtime dependencies.
Source: https://foi.tfl.gov.uk/FOI-0601-2425/Standard%20Tube%20map%20-%20December%202023%28a%29.svg
"""
import copy
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'index.html'
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
source = ET.parse(sys.argv[1]).getroot()
groups = source.find(f'{{{NS}}}switch/{{{NS}}}g')
data = json.loads(re.search(r'const DATA = (.*);', HTML.read_text())[1])
names = {n[0] for n in data['n'] if n[0]}
normalize = lambda n: re.sub(r'[^a-z0-9]', '', n.lower().replace('saint', 'st'))
by_normal = {normalize(n): n for n in names}
aliases = {'heathrowterminals23': 'Heathrow Terminals 2 & 3',
           'kingscrossstpancrasinternational': "King's Cross St. Pancras",
           'cuttysarkformaritimegreenwich': 'Cutty Sark', 'towerhillfenchurchst': 'Tower Hill'}

def ids(element):
    raw = re.sub(r'_x([0-9A-Fa-f]{2})_', lambda m: chr(int(m[1], 16)), element.get('id', ''))
    return re.findall(r'9[14]0G[A-Z0-9]+', raw)

id_names = {}
for label in next(g for g in groups if g.get('id') == 'station-names').iter():
    text = ' '.join(t.strip() for t in label.itertext() if t.strip())
    name = by_normal.get(normalize(text), aliases.get(normalize(text)))
    if name:
        for code in ids(label):
            id_names[code] = name
id_names.update({'940GZZLUOAK': 'Oakwood', '910GABWDXR': 'Abbey Wood',
                 '910GWOLWXR': 'Woolwich', '940GZZDLWLA': 'Woolwich Arsenal',
                 '910GWHCHPL': 'Whitechapel', '910GCUSTMHS': 'Custom House',
                 '940GZZDLCUS': 'Custom House', '910GWCHAPXR': 'Whitechapel',
                 '910GWPL': 'Whitechapel', '940GWPL': 'Whitechapel',
                 '910GWCROYDN': 'West Croydon', '910GLIVST': 'Liverpool Street',
                 '910GGNRSBRY': 'Gunnersbury', '940GZZLUGNRSBRY': 'Gunnersbury',
                 '910GNWEMBLY': 'North Wembley', '910GSKENTON': 'South Kenton',
                 '910GKENSLG': 'Kensal Green', '910GSTNBGPK': 'Stonebridge Park',
                 '910GHARLSDN': 'Harlesden'})

def bounds(element):
    wrapper = ET.Element(f'{{{NS}}}svg', {'width': '1247.2', 'height': '946.1'})
    element = copy.deepcopy(element)
    for e in element.iter():
        if e.tag.split('}')[-1] in ('polyline', 'polygon'):
            coords = re.findall(r'-?\d+(?:\.\d+)?', e.get('points', ''))
            e.set('d', 'M'+' L'.join(' '.join(coords[i:i+2]) for i in range(0, len(coords), 2)))
            e.tag = f'{{{NS}}}path'
            e.attrib.pop('points', None)
    wrapper.append(element)
    svg = pymupdf.open(stream=ET.tostring(wrapper), filetype='svg')
    pdf = pymupdf.open(stream=svg.convert_to_pdf(), filetype='pdf')
    drawings = pdf[0].get_drawings()
    if not drawings:
        return None
    box = pymupdf.Rect(drawings[0]['rect'])
    for drawing in drawings[1:]:
        box |= drawing['rect']
    return box

points = {n: [] for n in names}
ticks = set()

def add_point(name, x, y):
    if not any((x-p[0])**2 + (y-p[1])**2 < 2**2 for p in points[name]):
        points[name].append([round(x, 2), round(y, 2)])

line_ids = {'lul-bakerloo': 1, 'lul-central': 2, 'lul-circle': 3, 'lul-district': 4,
            'lul-hammersmith-city': 6, 'lul-jubilee': 7, 'lul-metropolitan': 8,
            'lul-northern': 9, 'lul-piccadilly': 10, 'lul-victoria': 11,
            'lul-waterloo-city': 12, 'dlr-dlr': 13, 'elizabeth': 14, 'raillo-overground': 0}
services = {n: set() for n in names}
for n in data['n']:
    if n[0]:
        services[n[0]].update(n[5])

art = ET.Element('g')
river = copy.deepcopy(next(g for g in groups if g.get('id') == 'river'))
art.append(river)
for e in river.iter():
    for attr in ('fill', 'stroke'):
        if e.get(attr) and e.get(attr) != 'none':
            e.set(attr, 'var(--river)')

for group in groups:
    if group.get('id') not in line_ids:
        continue
    for tick in group.iter():
        codes = ids(tick)
        if len(codes) == 1 and codes[0] in id_names:
            box = bounds(tick)
            if box and max(box.width, box.height) < 5:
                x, y = round((box.x0+box.x1)/2, 2), round((box.y0+box.y1)/2, 2)
                add_point(id_names[codes[0]], x, y)
                ticks.add((x, y))
    line = line_ids[group.get('id')]
    out = ET.SubElement(art, 'g')
    for item in group:
        codes = ids(item)
        mapped = [id_names[c] for c in codes if c in id_names]
        # Single-station elements are the little ticks, not track segments.
        if len(codes) == 1 or (len(mapped) == len(codes) and len(set(mapped)) == 1):
            box = bounds(item)
            if mapped and box and max(box.width, box.height) < 10:
                add_point(mapped[0], (box.x0+box.x1)/2, (box.y0+box.y1)/2)
            continue
        item = copy.deepcopy(item)
        service = line
        if line == 0:
            common = set(range(21, 27))
            for name in mapped:
                common &= services[name]
            if len(common) == 1:
                service = common.pop()
            elif '910GHGHI' in codes and '910GCNNB' in codes:
                service = 23 if item.get('id').endswith('_1_') else 26
            else:
                # White centre stripes may span several branches.
                service = 23
        for e in item.iter():
            for attr in ('fill', 'stroke'):
                color = e.get(attr, '').upper()
                if color in ('#FFFFFF', '#FFF', '#F1F2F2'):
                    e.set(attr, 'var(--land)')
                elif color and color != 'NONE':
                    e.set(attr, f'var(--line-{service})')
        out.append(item)

def markers(element, inherited=()):
    # Illustrator reuses some erroneous child IDs. A named station's outer group wins.
    inherited_names = set(id_names[c] for c in inherited if c in id_names)
    codes = inherited if len(inherited_names) == 1 and inherited_names != {'Bank'} else ids(element) or inherited
    mapped = set(id_names[c] for c in codes if c in id_names)
    if element.tag == f'{{{NS}}}path' and len(mapped) == 1:
        box = bounds(element)
        if box and 5.3 < box.width < 7.8 and 5.3 < box.height < 7.8 and abs(box.width-box.height) < .4:
            add_point(next(iter(mapped)), (box.x0+box.x1)/2, (box.y0+box.y1)/2)
    for child in element:
        markers(child, codes)

markers(next(g for g in groups if g.get('id') == 'interchange-circles'))
# These two station symbols have missing/misassigned IDs in the published SVG.
add_point('Debden', 871.1, 152.4)
add_point('Park Royal', 225, 428.7)
add_point('Wimbledon Park', 376.6, 627.2)
# The source also contains three duplicated symbols carrying another stop's ID.
for name, duplicate in [('Beckton', [908.4,542.5]), ('Gallions Reach', [908.4,526.0]),
                        ('Seven Sisters', [682.4,257.0])]:
    points[name] = [p for p in points[name] if p != duplicate]
missing = sorted(n for n, p in points.items() if not p)
print('Missing station markers:', missing)
if missing:
    raise ValueError('Every game station must have a diagram marker')
Path('/tmp/mtm-points.json').write_text(json.dumps(points, indent=2))
Path('/tmp/mtm-id-names.json').write_text(json.dumps(id_names, indent=2))
# Strip Illustrator metadata and IDs; only inert geometry goes into the game.
for e in art.iter():
    for child in list(e):
        if child.tag.split('}')[-1] not in {'g', 'path', 'line', 'rect', 'polyline', 'polygon', 'circle', 'ellipse'}:
            e.remove(child)
    e.tag = e.tag.split('}')[-1]
    e.attrib.pop('id', None)
    e.text = None
    e.tail = None
    if e.tag in ('polyline', 'polygon'):
        coords = re.findall(r'-?\d+(?:\.\d+)?', e.get('points', ''))
        e.set('d', 'M'+' L'.join(' '.join(coords[i:i+2]) for i in range(0, len(coords), 2)) + (' Z' if e.tag == 'polygon' else ''))
        e.tag = 'path'
        e.attrib.pop('points', None)
markup = ET.tostring(art, encoding='unicode')
# Ticks sit beside tracks in TfL's artwork. The game's circular targets must sit
# on the tracks, so project only those tick centres onto the nearest rail path.
rail_art = copy.deepcopy(art)
rail_art.remove(rail_art[0])  # exclude the river from the projection
rail_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1247.2" height="946.1">'+ET.tostring(rail_art, encoding='unicode')+'</svg>'
rail_svg = re.sub(r'var\(--[^)]+\)', '#000000', rail_svg)
rail_doc = pymupdf.open(stream=rail_svg.encode(), filetype='svg')
rail_pdf = pymupdf.open(stream=rail_doc.convert_to_pdf(), filetype='pdf')
segments = []
for drawing in rail_pdf[0].get_drawings():
    if not drawing['color'] or not 2 < (drawing['width'] or 0) < 2.5:
        continue
    for item in drawing['items']:
        if item[0] == 'l':
            segments.append((item[1], item[2]))
        elif item[0] == 'c':
            a,b,c,d = item[1:]
            samples = [a*(1-t)**3+b*(3*t*(1-t)**2)+c*(3*t*t*(1-t))+d*t**3 for t in [i/16 for i in range(17)]]
            segments.extend(zip(samples, samples[1:]))
def project(p, a, b):
    dx,dy = b.x-a.x,b.y-a.y
    t = max(0,min(1,((p[0]-a.x)*dx+(p[1]-a.y)*dy)/(dx*dx+dy*dy or 1)))
    return [a.x+t*dx,a.y+t*dy]
for name, locations in points.items():
    for i,p in enumerate(locations):
        if tuple(p) in ticks:
            near = min((project(p,a,b) for a,b in segments), key=lambda q:(p[0]-q[0])**2+(p[1]-q[1])**2)
            if (p[0]-near[0])**2+(p[1]-near[1])**2 < 16:
                locations[i] = [round(v,2) for v in near]
    points[name] = [p for i,p in enumerate(locations) if not any((p[0]-q[0])**2+(p[1]-q[1])**2 < 4 for q in locations[:i])]
Path('/tmp/mtm-art.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1247.2 946.1">'+markup+'</svg>')
Path('/tmp/mtm-diagram.json').write_text(json.dumps({'points': points, 'art': markup}, separators=(',', ':')))
# Sample the published paths once at build time. The animation can then deform
# both layouts without SVG path APIs or per-frame geometry measurements.
colors = {f'var(--line-{i})': i for i in list(line_ids.values()) + list(range(21,27))}
colors.update({'var(--river)': 100, 'var(--land)': 101})
sample_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1247.2" height="946.1">'+markup+'</svg>'
for color, code in colors.items():
    sample_svg = sample_svg.replace(color, f'#{code:06x}')
sample_doc = pymupdf.open(stream=sample_svg.encode(), filetype='svg')
sample_pdf = pymupdf.open(stream=sample_doc.convert_to_pdf(), filetype='pdf')
reverse_colors = {code: color for color,code in colors.items()}
def css_color(rgb):
    if rgb is None:
        return 'none'
    r,g,b = [round(c*255) for c in rgb]
    return reverse_colors.get((r<<16)+(g<<8)+b, 'var(--ink)')
morph_paths = []
for drawing in sample_pdf[0].get_drawings():
    runs, run = [], []
    for item in drawing['items']:
        if item[0] == 're':
            rect = item[1]
            segments_to_sample = [('l',a,b) for a,b in zip([rect.tl,rect.tr,rect.br,rect.bl],[rect.tr,rect.br,rect.bl,rect.tl])]
        else:
            segments_to_sample = [item]
        for seg in segments_to_sample:
            if seg[0] not in ('l','c'):
                continue
            a,b = seg[1],seg[-1]
            if run and math.dist(run[-1],a) > .01:
                runs.append(run); run=[]
            if not run:
                run.append(list(a))
            length = sum(abs(v-u) for u,v in zip(seg[1:],seg[2:]))
            count = max(1, math.ceil(length/5))
            for i in range(1,count+1):
                t=i/count
                p=a*(1-t)+b*t if seg[0]=='l' else a*(1-t)**3+seg[2]*(3*t*(1-t)**2)+seg[3]*(3*t*t*(1-t))+b*t**3
                run.append(list(p))
    if run:
        if drawing['closePath']:
            run.append(run[0])
        runs.append(run)
    if runs:
        morph_paths.append({'runs': [[[round(v*20,2) for v in p] for p in run] for run in runs],
                            'fill': css_color(drawing['fill']), 'stroke': css_color(drawing['color']),
                            'width': round((drawing['width'] or 0)*20,3)})
payload = json.dumps({'points': dict(sorted(points.items())), 'art': markup, 'morphPaths': morph_paths}, separators=(',', ':'))
html = HTML.read_text()
declaration = 'const SCHEMATIC = '+payload+';'
if 'const SCHEMATIC = ' in html:
    html = re.sub(r'^const SCHEMATIC = .*;$', lambda _: declaration, html, flags=re.M)
else:
    html = html.replace('const THAMES = ', declaration+'\nconst THAMES = ')
HTML.write_text(html)
