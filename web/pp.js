// สร้างข้อมูล QR พร้อมเพย์ (มาตรฐาน EMVCo / Thai QR)
function promptpayPayload(id, amount) {
  let acc = String(id).replace(/\D/g, '');
  const tag = acc.length >= 15 ? '03' : acc.length >= 13 ? '02' : '01';
  if (tag === '01') acc = ('0000000000000' + acc.replace(/^0/, '66')).slice(-13);
  const f = (t, v) => t + String(v.length).padStart(2, '0') + v;
  let p = f('00', '01') + f('01', amount ? '12' : '11') + f('29', f('00', 'A000000677010111') + f(tag, acc)) + f('58', 'TH') + f('53', '764');
  if (amount) p += f('54', Number(amount).toFixed(2));
  p += '6304';
  let crc = 0xffff;
  for (let i = 0; i < p.length; i++) {
    crc ^= p.charCodeAt(i) << 8;
    for (let k = 0; k < 8; k++) crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
  }
  return p + crc.toString(16).toUpperCase().padStart(4, '0');
}
if (typeof module !== 'undefined') module.exports = promptpayPayload;
