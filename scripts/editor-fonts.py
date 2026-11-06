"""Fetch only six pinned fonts (under 3 MiB), with licenses and blob checks."""
from pathlib import Path
import hashlib
import json
import urllib.request

target = Path(__file__).resolve().parent.parent/'static/editor-assets/fonts'
target.mkdir(parents=True, exist_ok=True)
revision = 'b048ac917adba5ea448a7863a6b42a2a51eacbef'
assets = {
    'fonts/DejaVuSansMono.ttf':'f5786022f18216b4c59c6fb0c634b52c8b6e7990',
    'fonts/LibertinusSerif-Bold.otf':'37fbe05403ee745b29a039bdf782a7237be227e5',
    'fonts/LibertinusSerif-BoldItalic.otf':'eb34c4e01f57a25d948f42b44569bb29bb0666b8',
    'fonts/LibertinusSerif-Italic.otf':'cd3118d8df23111357ee6976c28c1ee56a376811',
    'fonts/LibertinusSerif-Regular.otf':'508f3c0fd3dc262eaff3d470241a37f8451f3ecb',
    'fonts/NewCMMath-Regular.otf':'82221fb81144de415b9d022767ce0c7eebb4a93b',
    'LICENSES/DejaVuSansMono-LICENSE.txt':'e7af79760c65d2c04d40dfd0f260f9b47363b09c',
    'LICENSES/Libertinus-OFL.txt':'badf3719f8dec2bc91eaa5613f5e7aed9355e758',
    'LICENSES/NewComputerModern-GUST-1.0.txt':'0a8cf33ad0e516c79975a607d9834f75a672ff80',
}
for path, expected in assets.items():
    destination = target/Path(path).name
    raw = destination.read_bytes() if destination.exists() else urllib.request.urlopen(
        f'https://raw.githubusercontent.com/TeXlyre/texlyre-font-assets/{revision}/{path}', timeout=30).read(2*1024*1024)
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=expected:
        raise ValueError('Font asset integrity check failed: '+path)
    destination.write_bytes(raw)
(target/'fonts.json').write_text(json.dumps([Path(p).name for p in assets if p.startswith('fonts/')]), encoding='utf-8')
print('Six local editor fonts and their licenses are ready.')
