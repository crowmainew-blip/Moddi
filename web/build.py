import base64, re, os, shutil, sys
H=os.path.dirname(os.path.abspath(__file__))
t=open(f'{H}/template.html', encoding='utf-8').read()
parts={'/*__ICONS__*/':open(f'{H}/icons.js', encoding='utf-8').read(),
 '/*__QRCODE__*/':open(f'{H}/vendor/qrcode.js', encoding='utf-8').read(),
 '/*__PROMPTPAY__*/':open(f'{H}/pp.js', encoding='utf-8').read(),'/*__ENGINE__*/':open(f'{H}/engine.js', encoding='utf-8').read(),
 '/*__GUIDES__*/':open(f'{H}/guides.js', encoding='utf-8').read(),
 '__LOGO64__':base64.b64encode(open(f'{H}/logo-64.png','rb').read()).decode(),
 '__FAVICON__':base64.b64encode(open(f'{H}/favicon-32.png','rb').read()).decode(),
 '__FONT_B64__':base64.b64encode(open(f'{H}/ThaiGameFont.woff','rb').read()).decode()}
for k,v in parts.items(): t=t.replace(k,v)
open(f'{H}/site/index.html','w', encoding='utf-8').write(t)
print('built', len(t))
