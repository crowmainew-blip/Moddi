import base64, re, os, shutil, sys
H=os.path.dirname(os.path.abspath(__file__))
t=open(f'{H}/template.html').read()
parts={'/*__ICONS__*/':open(f'{H}/icons.js').read(),
 '/*__QRCODE__*/':open(f'{H}/vendor/qrcode.js').read(),
 '/*__PROMPTPAY__*/':open(f'{H}/pp.js').read(),'/*__ENGINE__*/':open(f'{H}/engine.js').read(),
 '/*__GUIDES__*/':open(f'{H}/guides.js').read(),
 '__LOGO64__':base64.b64encode(open(f'{H}/logo-64.png','rb').read()).decode(),
 '__FAVICON__':base64.b64encode(open(f'{H}/favicon-32.png','rb').read()).decode(),
 '__FONT_B64__':base64.b64encode(open(f'{H}/ThaiGameFont.woff','rb').read()).decode()}
for k,v in parts.items(): t=t.replace(k,v)
open(f'{H}/site/index.html','w').write(t)
print('built', len(t))
