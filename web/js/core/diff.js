/**
 * 纯前端文本 diff（版本对比用）。
 * 不依赖第三方库、不上传正文；短文本按字符 diff，长文本按行/句 diff。
 */

function toText(v) {
  return v === undefined || v === null ? '' : String(v);
}

/** 按行切分；单行长文按中文句末标点再切，避免整段一红一绿看不清。 */
export function splitUnits(text) {
  const s = toText(text).replace(/\r\n/g, '\n');
  if (!s) return [];
  let lines = s.split('\n');
  if (lines.length === 1 && lines[0].length > 80) {
    lines = lines[0].split(/(?<=[。！？!?；;])/).filter((x) => x !== '');
  }
  return lines;
}

/**
 * 行级 LCS diff。
 * @returns {{type:'same'|'del'|'add', text:string}[]}
 */
export function diffUnits(aText, bText) {
  const a = splitUnits(aText);
  const b = splitUnits(bText);
  const n = a.length;
  const m = b.length;
  // dp[i][j] = a[i:] 与 b[j:] 的 LCS 长度
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ type: 'same', text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ type: 'del', text: a[i] });
      i += 1;
    } else {
      out.push({ type: 'add', text: b[j] });
      j += 1;
    }
  }
  while (i < n) { out.push({ type: 'del', text: a[i] }); i += 1; }
  while (j < m) { out.push({ type: 'add', text: b[j] }); j += 1; }
  return out;
}

/** 并排展示：把 del/add 分别放到左/右列，空位用 empty 占位 */
export function sideBySide(aText, bText) {
  const ops = diffUnits(aText, bText);
  const left = [];
  const right = [];
  let added = 0;
  let removed = 0;
  ops.forEach((op) => {
    if (op.type === 'same') {
      left.push({ type: 'same', text: op.text });
      right.push({ type: 'same', text: op.text });
    } else if (op.type === 'del') {
      left.push({ type: 'del', text: op.text });
      right.push({ type: 'empty', text: '' });
      removed += 1;
    } else {
      left.push({ type: 'empty', text: '' });
      right.push({ type: 'add', text: op.text });
      added += 1;
    }
  });
  return { left, right, stats: { added, removed, same: ops.length - added - removed } };
}

/**
 * 短文本字符级 diff（标题/话题）。
 * @returns {{left:{type,text}[], right:{type,text}[], stats:{added,removed}}}
 */
export function inlineDiff(aText, bText) {
  const a = Array.from(toText(aText));
  const b = Array.from(toText(bText));
  const n = a.length;
  const m = b.length;
  if (n * m > 4000000) {
    // 超长文本退回行级，避免卡顿
    return sideBySide(aText, bText);
  }
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: 'same', text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: 'del', text: a[i] });
      i += 1;
    } else {
      ops.push({ type: 'add', text: b[j] });
      j += 1;
    }
  }
  while (i < n) { ops.push({ type: 'del', text: a[i] }); i += 1; }
  while (j < m) { ops.push({ type: 'add', text: b[j] }); j += 1; }

  const left = [];
  const right = [];
  let added = 0;
  let removed = 0;
  ops.forEach((op) => {
    if (op.type === 'same') {
      left.push(op);
      right.push(op);
    } else if (op.type === 'del') {
      left.push(op);
      removed += 1;
    } else {
      right.push(op);
      added += 1;
    }
  });
  return { left, right, stats: { added, removed } };
}

/** 文本是否完全相同 */
export function sameText(a, b) {
  return toText(a) === toText(b);
}
