// moddi web engine — ติดตั้ง/ถอน mod สำหรับ RPG Maker MV/MZ ผ่าน File System Access API
// พฤติกรรมเหมือน core/rpgmaker.py ทุกอย่าง (รูปแบบ backup เดียวกัน ใช้สลับกับโปรแกรมได้)
const Moddi = (() => {
  const BACKUP_DIR = 'moddi_backup';
  const FONT_NAME = 'ThaiGameFont.woff';
  const MOD_FORMAT = 'moddi/1';
  const OLD_FORMATS = ['thaimod/1'];
  const DB_FIELDS = {
    'Actors.json': ['name', 'nickname', 'profile'],
    'Classes.json': ['name'],
    'Skills.json': ['name', 'description', 'message1', 'message2'],
    'Items.json': ['name', 'description'],
    'Weapons.json': ['name', 'description'],
    'Armors.json': ['name', 'description'],
    'Enemies.json': ['name'],
    'States.json': ['name', 'message1', 'message2', 'message3', 'message4'],
  };
  const SYSTEM_LISTS = ['elements', 'skillTypes', 'weaponTypes', 'armorTypes', 'equipTypes'];
  const TERM_LISTS = ['basic', 'commands', 'params'];

  // ---------------------------------------------------------- file helpers
  async function sub(dir, name, create = false) {
    try { return await dir.getDirectoryHandle(name, { create }); } catch { return null; }
  }
  async function fileH(dir, name) {
    try { return await dir.getFileHandle(name); } catch { return null; }
  }
  async function readBytes(dir, name) { return new Uint8Array(await (await (await dir.getFileHandle(name)).getFile()).arrayBuffer()); }
  async function readJSON(dir, name) {
    let t = new TextDecoder('utf-8').decode(await readBytes(dir, name));
    if (t.charCodeAt(0) === 0xfeff) t = t.slice(1);
    return JSON.parse(t);
  }
  async function write(dir, name, data) {
    const w = await (await dir.getFileHandle(name, { create: true })).createWritable();
    await w.write(data); await w.close();
  }
  async function list(dir) {
    const out = [];
    for await (const [name, h] of dir.entries()) out.push({ name, h });
    return out.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  }
  async function copyTree(src, dst) {
    for (const { name, h } of await list(src)) {
      if (h.kind === 'directory') await copyTree(h, await dst.getDirectoryHandle(name, { create: true }));
      else await write(dst, name, await readBytes(src, name));
    }
  }

  // ---------------------------------------------------------- detect
  async function detect(gameDir) {
    const www = await sub(gameDir, 'www');
    for (const [root, isWww] of [[gameDir, false], [www, true]]) {
      if (!root) continue;
      const data = await sub(root, 'data');
      if (!data || !(await fileH(data, 'System.json'))) continue;
      const js = await sub(root, 'js');
      let engine;
      if (js && (await fileH(js, 'rmmz_core.js'))) engine = 'RPG Maker MZ';
      else if (js && (await fileH(js, 'rpg_core.js'))) engine = 'RPG Maker MV';
      else engine = isWww ? 'RPG Maker MV' : 'RPG Maker MZ';
      const backup = await sub(root, BACKUP_DIR);
      const bdata = backup && (await sub(backup, 'data'));
      const sys = await readJSON(bdata && (await fileH(bdata, 'System.json')) ? bdata : data, 'System.json');
      return { engine, root, data, bdata, title: sys.gameTitle || '', installed: !!bdata };
    }
    return null;
  }

  // ---------------------------------------------------------- walk (เหมือน Python)
  const isText = s => typeof s === 'string' && s.trim() !== '';
  const or = (a, b) => (a ? a : b);

  function walkEvents(cmds, visit, ctx) {
    const out = [];
    let i = 0;
    while (i < cmds.length) {
      const c = cmds[i], code = c.code;
      if (code === 401 || code === 405) {
        let j = i; const lines = [];
        while (j < cmds.length && cmds[j].code === code) {
          const p = cmds[j].parameters;
          lines.push(p && p.length ? p[0] : '');
          j++;
        }
        const block = lines.join('\n');
        const nw = isText(block) ? visit(block, code === 401 ? 'dialogue' : 'scroll', ctx) : null;
        if (!nw) for (let k = i; k < j; k++) out.push(cmds[k]);
        else for (const line of nw.split('\n')) out.push({ code, indent: c.indent ?? 0, parameters: [line] });
        i = j; continue;
      }
      const p = [...(c.parameters || [])];
      if (code === 101 && p.length > 4 && isText(p[4])) p[4] = or(visit(p[4], 'speaker', ctx), p[4]);
      else if (code === 102 && p.length && Array.isArray(p[0])) p[0] = p[0].map(s => (isText(s) ? or(visit(s, 'choice', ctx), s) : s));
      else if (code === 402 && p.length > 1 && isText(p[1])) p[1] = or(visit(p[1], 'choice', ctx), p[1]);
      else if ([320, 324, 325].includes(code) && p.length > 1 && isText(p[1])) p[1] = or(visit(p[1], 'name', ctx), p[1]);
      out.push({ ...c, parameters: p });
      i++;
    }
    return out;
  }

  function walkFile(name, obj, visit) {
    const ctx = { file: name };
    const mapList = (arr, kind) => arr.map(s => (isText(s) ? or(visit(s, kind, ctx), s) : s));
    if (DB_FIELDS[name]) {
      for (const row of obj) {
        if (!row || typeof row !== 'object' || !Object.keys(row).length) continue;
        for (const k of DB_FIELDS[name]) if (isText(row[k])) row[k] = or(visit(row[k], 'db', ctx), row[k]);
      }
    } else if (name === 'System.json') {
      if (isText(obj.gameTitle)) obj.gameTitle = or(visit(obj.gameTitle, 'title', ctx), obj.gameTitle);
      if (isText(obj.currencyUnit)) obj.currencyUnit = or(visit(obj.currencyUnit, 'term', ctx), obj.currencyUnit);
      for (const k of SYSTEM_LISTS) if (Array.isArray(obj[k])) obj[k] = mapList(obj[k], 'term');
      const terms = obj.terms || {};
      for (const k of TERM_LISTS) if (Array.isArray(terms[k])) terms[k] = mapList(terms[k], 'term');
      const msgs = terms.messages || {};
      for (const k of Object.keys(msgs)) if (isText(msgs[k])) msgs[k] = or(visit(msgs[k], 'term', ctx), msgs[k]);
    } else if (name === 'CommonEvents.json') {
      for (const ev of obj) if (ev && Array.isArray(ev.list)) ev.list = walkEvents(ev.list, visit, ctx);
    } else if (name === 'Troops.json') {
      for (const tr of obj) for (const pg of (tr || {}).pages || []) pg.list = walkEvents(pg.list || [], visit, ctx);
    } else if (/^Map\d+\.json$/.test(name)) {
      if (isText(obj.displayName)) obj.displayName = or(visit(obj.displayName, 'map', ctx), obj.displayName);
      for (const ev of obj.events || []) for (const pg of (ev || {}).pages || []) pg.list = walkEvents(pg.list || [], visit, ctx);
    }
    return obj;
  }

  async function jsonNames(dir) {
    return (await list(dir)).filter(e => e.h.kind === 'file' && e.name.endsWith('.json')).map(e => e.name);
  }

  // ---------------------------------------------------------- API
  async function extract(info) {
    const src = info.bdata || info.data;
    const seen = new Set();
    for (const name of await jsonNames(src)) {
      walkFile(name, await readJSON(src, name), t => { seen.add(t); return null; });
    }
    return seen;
  }

  async function install(gameDir, entries, fontBytes, onStep = () => {}) {
    let info = await detect(gameDir);
    if (!info) throw new Error('ไม่เจอเกม RPG Maker MV/MZ ในโฟลเดอร์นี้');
    if (!info.installed) {
      onStep('กำลังสำรองไฟล์เดิม...');
      const broot = await info.root.getDirectoryHandle(BACKUP_DIR, { create: true });
      await copyTree(info.data, await broot.getDirectoryHandle('data', { create: true }));
      const fonts = await sub(info.root, 'fonts');
      if (fonts && (await fileH(fonts, 'gamefont.css'))) await write(broot, 'gamefont.css', await readBytes(fonts, 'gamefont.css'));
      info = await detect(gameDir);
    }
    let count = 0;
    const visit = t => { const v = entries[t]; if (v && v !== t) { count++; return v; } return null; };
    const names = await jsonNames(info.bdata);
    for (let i = 0; i < names.length; i++) {
      const name = names[i];
      onStep(`กำลังใส่คำแปล ${i + 1}/${names.length}`);
      const obj = walkFile(name, await readJSON(info.bdata, name), visit);
      if (name === 'System.json' && info.engine === 'RPG Maker MZ') {
        obj.advanced = obj.advanced || {};
        obj.advanced.mainFontFilename = FONT_NAME;
      }
      await write(info.data, name, JSON.stringify(obj));
    }
    onStep('กำลังใส่ฟอนต์ไทย...');
    const fonts = await info.root.getDirectoryHandle('fonts', { create: true });
    await write(fonts, FONT_NAME, fontBytes);
    if (info.engine === 'RPG Maker MV') {
      await write(fonts, 'gamefont.css', '@font-face {\n    font-family: GameFont;\n    src: url("' + FONT_NAME + '");\n}\n');
    }
    return count;
  }

  async function uninstall(gameDir) {
    const info = await detect(gameDir);
    if (!info || !info.installed) throw new Error('เกมนี้ยังไม่ได้ติดตั้ง mod');
    const broot = await info.root.getDirectoryHandle(BACKUP_DIR);
    await info.root.removeEntry('data', { recursive: true });
    await copyTree(info.bdata, await info.root.getDirectoryHandle('data', { create: true }));
    const fonts = await sub(info.root, 'fonts');
    if (await fileH(broot, 'gamefont.css')) await write(fonts, 'gamefont.css', await readBytes(broot, 'gamefont.css'));
    if (fonts && (await fileH(fonts, FONT_NAME))) await fonts.removeEntry(FONT_NAME);
    await info.root.removeEntry(BACKUP_DIR, { recursive: true });
  }

  function readMod(text) {
    if (text.length > 50 * 1024 * 1024) throw new Error('ไฟล์ mod ใหญ่เกินไป');
    let data;
    try { data = JSON.parse(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text); }
    catch { throw new Error('ไฟล์นี้ไม่ใช่ไฟล์ mod (ต้องเป็น .moddi.json)'); }
    if (!data || typeof data !== 'object' || (data.format !== MOD_FORMAT && !OLD_FORMATS.includes(data.format))) throw new Error('รูปแบบไฟล์ mod ไม่ถูกต้อง');
    if (!data.entries || typeof data.entries !== 'object' || Array.isArray(data.entries)) throw new Error('ไฟล์ mod ไม่มีคำแปล');
    const entries = Object.create(null);
    for (const [k, v] of Object.entries(data.entries)) {
      if (typeof v !== 'string') throw new Error('ไฟล์ mod มีข้อมูลที่ไม่ใช่ข้อความ');
      if (v.length > 10000 || /<\s*script/i.test(v)) throw new Error('ไฟล์ mod มีเนื้อหาน่าสงสัย');
      entries[k] = v;
    }
    const origin = Object.create(null);
    if (data.origin && typeof data.origin === 'object')
      for (const [k, v] of Object.entries(data.origin)) if (k in entries && ['f', 'p', 'h'].includes(v)) origin[k] = v;
    return { title: String(data.title || ''), translator: String(data.translator || ''), engine: String(data.engine || ''),
             created: String(data.created || ''), entries, origin };
  }

  return { detect, extract, install, uninstall, readMod };
})();
if (typeof module !== 'undefined') module.exports = Moddi;
