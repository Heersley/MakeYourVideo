#!/usr/bin/env node
'use strict';

// PreToolUse safety gate for Antigravity run_command:
// 1. Hard-deny `git gc` / `git prune` to protect repository history & unreferenced objects.
// 2. Force interactive host confirmation (`force_ask`) on `episode.py approve` so no agent
//    can silently self-approve Director review/delivery gates even under Always-Allow.

const path = require('node:path');

const GIT_FLAGS_WITH_VALUE = new Set([
  '-c',
  '-C',
  '--git-dir',
  '--work-tree',
  '--namespace',
  '--config-env',
  '--super-prefix',
  '--exec-path',
  '--list-cmds',
]);

function splitSegments(cmd) {
  const segments = [];
  let cur = '';
  let quote = null;
  for (let i = 0; i < cmd.length; i++) {
    const ch = cmd[i];
    if (quote) {
      cur += ch;
      if (ch === '\\' && quote === '"' && i + 1 < cmd.length) {
        cur += cmd[++i];
      } else if (ch === '`' && quote === '"' && i + 1 < cmd.length) {
        cur += cmd[++i];
      } else if (ch === quote) {
        quote = null;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      cur += ch;
      continue;
    }
    if (ch === ';' || ch === '\r' || ch === '\n') {
      if (cur.trim()) segments.push(cur.trim());
      cur = '';
      continue;
    }
    if (ch === '&' || ch === '|') {
      const next = cmd[i + 1];
      if (next === ch) {
        if (cur.trim()) segments.push(cur.trim());
        cur = '';
        i++;
        continue;
      }
      if (ch === '|') {
        if (cur.trim()) segments.push(cur.trim());
        cur = '';
        continue;
      }
    }
    cur += ch;
  }
  if (cur.trim()) segments.push(cur.trim());
  return segments;
}

function tokenize(segment) {
  const tokens = [];
  let cur = '';
  let quote = null;
  let inToken = false;
  for (let i = 0; i < segment.length; i++) {
    const ch = segment[i];
    if (quote) {
      if ((ch === '\\' || ch === '`') && quote === '"' && i + 1 < segment.length) {
        cur += segment[++i];
      } else if (ch === quote) {
        quote = null;
      } else {
        cur += ch;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      inToken = true;
      continue;
    }
    if (/\s/.test(ch)) {
      if (inToken) {
        tokens.push(cur);
        cur = '';
        inToken = false;
      }
      continue;
    }
    cur += ch;
    inToken = true;
  }
  if (inToken) tokens.push(cur);
  return tokens;
}

function normalizeExe(token) {
  const base = path.win32.basename(token).toLowerCase();
  return base;
}

function isGitExecutable(token) {
  const lower = token.toLowerCase();
  if (lower === '$git' || lower === '${git}') return true;
  const base = normalizeExe(token);
  return base === 'git' || base === 'git.exe';
}

function isPythonExecutable(token) {
  const lower = token.toLowerCase();
  if (lower === '$python' || lower === '${python}') return true;
  const base = normalizeExe(token);
  return /^(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?$/.test(base);
}

function stripLeadingWrappers(tokens) {
  let idx = 0;
  while (idx < tokens.length) {
    const t = tokens[idx];
    if (t === '&' || t === '.' || t === 'call') {
      idx++;
      continue;
    }
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(t)) {
      idx++;
      continue;
    }
    break;
  }
  return tokens.slice(idx);
}

function findGitSubcommand(args) {
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--') return args[i + 1] || null;
    if (GIT_FLAGS_WITH_VALUE.has(a)) {
      i++;
      continue;
    }
    if (a.startsWith('-')) continue;
    return a.toLowerCase();
  }
  return null;
}

function checkSegment(segment) {
  const tokens = stripLeadingWrappers(tokenize(segment));
  if (!tokens.length) return null;

  const exe = tokens[0];
  const args = tokens.slice(1);

  if (isGitExecutable(exe)) {
    const sub = findGitSubcommand(args);
    if (sub === 'gc' || sub === 'prune') {
      return {
        decision: 'deny',
        reason: `工程红线拦截：禁止对 .git 执行 git ${sub}。`,
      };
    }
  }

  // Direct `episode.py approve` or `python ... episode.py approve ...`
  const epIdx = tokens.findIndex((t) => normalizeExe(t) === 'episode.py');
  if (epIdx !== -1) {
    for (let i = epIdx + 1; i < tokens.length; i++) {
      const a = tokens[i];
      if (a.startsWith('-')) continue;
      if (a.toLowerCase() === 'approve') {
        return {
          decision: 'force_ask',
          reason:
            '人工签字卡点：即将执行 episode.py approve。请核对 --gate 与导演真实确认原话后再点击允许。',
        };
      }
      break;
    }
  }

  // Catch inline `python -c "... episode.py ... approve ..."` attempts
  if (isPythonExecutable(exe)) {
    const cIdx = args.indexOf('-c');
    if (cIdx !== -1 && typeof args[cIdx + 1] === 'string') {
      const code = args[cIdx + 1];
      if (/episode\.py/i.test(code) && /\bapprove\b/i.test(code)) {
        return {
          decision: 'force_ask',
          reason:
            '人工签字卡点：检测到脚本内联调用 episode.py approve，请人工核对后再点击允许。',
        };
      }
    }
  }

  return null;
}

function evaluateCommand(commandLine) {
  if (typeof commandLine !== 'string' || !commandLine.trim()) {
    return {decision: 'allow'};
  }
  let askResult = null;
  for (const seg of splitSegments(commandLine)) {
    const hit = checkSegment(seg);
    if (!hit) continue;
    if (hit.decision === 'deny') return hit;
    if (hit.decision === 'force_ask' && !askResult) askResult = hit;
  }
  return askResult || {decision: 'allow'};
}

if (require.main === module) {
  let raw = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => {
    raw += chunk;
  });
  process.stdin.on('end', () => {
    let result = {decision: 'allow'};
    try {
      const payload = JSON.parse(raw || '{}');
      const tc = payload.toolCall || {};
      if (tc.name === 'run_command' && tc.args && typeof tc.args.CommandLine === 'string') {
        result = evaluateCommand(tc.args.CommandLine);
      }
    } catch {
      result = {decision: 'allow'};
    }
    process.stdout.write(JSON.stringify(result) + '\n');
  });
}

module.exports = {evaluateCommand, splitSegments, tokenize};
