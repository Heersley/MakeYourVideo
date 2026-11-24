// Check only this episode and its transitive imports, using the installed compiler.
const path = require('node:path');
const ts = require('typescript');
const semver = require('semver');

const BANNED_FONT_GLOBAL_RE =
  /\b(?:Microsoft\s+YaHei|STZhongsong|SimHei|SimSun|NSimSun)\b|微软雅黑|华文中宋/i;
const BANNED_FONT_CONTEXT_RE = /(?:新?宋体|黑体)/;

function unwrapExpr(node) {
  let cur = node;
  while (cur) {
    if (
      ts.isParenthesizedExpression(cur) ||
      ts.isAsExpression(cur) ||
      ts.isTypeAssertionExpression(cur) ||
      ts.isNonNullExpression(cur) ||
      (ts.isSatisfiesExpression && ts.isSatisfiesExpression(cur))
    ) {
      cur = cur.expression;
      continue;
    }
    break;
  }
  return cur;
}

function getPropName(nameNode) {
  if (!nameNode) return null;
  if (ts.isIdentifier(nameNode) || ts.isStringLiteral(nameNode) || ts.isNumericLiteral(nameNode)) {
    return nameNode.text;
  }
  if (ts.isComputedPropertyName(nameNode)) {
    const inner = unwrapExpr(nameNode.expression);
    if (ts.isStringLiteral(inner) || ts.isNoSubstitutionTemplateLiteral(inner)) {
      return inner.text;
    }
  }
  return null;
}

function isFontContext(node) {
  let cur = node.parent;
  for (let depth = 0; cur && depth < 6; depth++, cur = cur.parent) {
    if (ts.isPropertyAssignment(cur)) {
      const name = getPropName(cur.name);
      if (name && /font[-_]?family|font$/i.test(name)) return true;
    }
    if (ts.isJsxAttribute(cur)) {
      const name = cur.name && cur.name.text;
      if (name && /font[-_]?family|font$/i.test(name)) return true;
    }
    if (ts.isVariableDeclaration(cur) && ts.isIdentifier(cur.name)) {
      if (/font/i.test(cur.name.text)) return true;
    }
  }
  return false;
}

function collectConstObjects(sf) {
  const map = new Map();
  function walk(node) {
    if (ts.isVariableStatement(node)) {
      const isConst = (node.declarationList.flags & ts.NodeFlags.Const) !== 0;
      if (isConst) {
        for (const decl of node.declarationList.declarations) {
          if (ts.isIdentifier(decl.name) && decl.initializer) {
            const expr = unwrapExpr(decl.initializer);
            if (ts.isObjectLiteralExpression(expr)) {
              map.set(decl.name.text, expr);
            }
          }
        }
      }
    }
    ts.forEachChild(node, walk);
  }
  walk(sf);
  return map;
}

function resolveObjectLiteral(expr, constMap, seen = new Set()) {
  const cur = unwrapExpr(expr);
  if (!cur) return null;
  if (ts.isObjectLiteralExpression(cur)) return cur;
  if (ts.isIdentifier(cur) && constMap.has(cur.text) && !seen.has(cur.text)) {
    seen.add(cur.text);
    return constMap.get(cur.text);
  }
  return null;
}

// Flatten an ObjectLiteralExpression (including resolvable `...CONST_OBJ` spreads) into
// `{ props: Map<string, ts.Expression>, hasUnresolvedSpread: boolean }`.
function inspectObject(objLit, constMap, seen = new Set()) {
  const props = new Map();
  let hasUnresolvedSpread = false;
  for (const prop of objLit.properties) {
    if (ts.isSpreadAssignment(prop)) {
      const target = resolveObjectLiteral(prop.expression, constMap, new Set(seen));
      if (target) {
        const merged = inspectObject(target, constMap, new Set(seen));
        for (const [k, v] of merged.props.entries()) props.set(k, v);
        if (merged.hasUnresolvedSpread) hasUnresolvedSpread = true;
      } else {
        hasUnresolvedSpread = true;
      }
    } else if (ts.isPropertyAssignment(prop)) {
      const key = getPropName(prop.name);
      if (key !== null) props.set(key, prop.initializer);
    } else if (ts.isShorthandPropertyAssignment(prop)) {
      props.set(prop.name.text, prop.name);
    }
  }
  return {props, hasUnresolvedSpread};
}

function collectRemotionSpringSymbols(sf) {
  const springIds = new Set();
  const remotionNamespaces = new Set();
  for (const stmt of sf.statements) {
    if (!ts.isImportDeclaration(stmt)) continue;
    const mod = stmt.moduleSpecifier;
    if (!ts.isStringLiteral(mod) || mod.text !== 'remotion') continue;
    const clause = stmt.importClause;
    if (!clause || !clause.namedBindings) continue;
    if (ts.isNamespaceImport(clause.namedBindings)) {
      remotionNamespaces.add(clause.namedBindings.name.text);
    } else if (ts.isNamedImports(clause.namedBindings)) {
      for (const spec of clause.namedBindings.elements) {
        const imported = spec.propertyName ? spec.propertyName.text : spec.name.text;
        if (imported === 'spring') springIds.add(spec.name.text);
      }
    }
  }
  return {springIds, remotionNamespaces};
}

function formatLocation(sf, node, baseDir) {
  const {line, character} = sf.getLineAndCharacterOfPosition(node.getStart(sf));
  const rel = path.relative(baseDir, sf.fileName).replace(/\\/g, '/');
  return `${rel}:${line + 1}:${character + 1}`;
}

function lintSourceFile(sf, baseDir) {
  const errors = [];
  const warnings = [];
  const constMap = collectConstObjects(sf);
  const {springIds, remotionNamespaces} = collectRemotionSpringSymbols(sf);

  function checkStringNode(node, text) {
    const globalMatch = BANNED_FONT_GLOBAL_RE.exec(text);
    if (globalMatch) {
      errors.push(
        `${formatLocation(sf, node, baseDir)} 禁止使用系统回退字体 "${globalMatch[0]}"（须使用离线四族字体）。`
      );
      return;
    }
    if (
      (/font-family\s*:/i.test(text) || isFontContext(node)) &&
      BANNED_FONT_CONTEXT_RE.test(text)
    ) {
      const m = BANNED_FONT_CONTEXT_RE.exec(text);
      errors.push(
        `${formatLocation(sf, node, baseDir)} 字体声明中禁止使用系统字体 "${m[0]}"（须使用离线四族字体）。`
      );
    }
  }

  function checkSpringCall(call) {
    const loc = formatLocation(sf, call, baseDir);
    if (!call.arguments.length) {
      errors.push(`${loc} remotion spring() 缺少参数，必须显式配置 config: { overshootClamping: true }。`);
      return;
    }
    const argObj = resolveObjectLiteral(call.arguments[0], constMap);
    if (!argObj) {
      warnings.push(
        `${loc} remotion spring() 参数为动态变量引用，无法静态校验 config.overshootClamping: true。`
      );
      return;
    }
    const top = inspectObject(argObj, constMap);
    if (!top.props.has('config')) {
      if (top.hasUnresolvedSpread) {
        warnings.push(
          `${loc} remotion spring() 参数含动态展开，无法静态校验 config.overshootClamping: true。`
        );
      } else {
        errors.push(
          `${loc} remotion spring() 必须显式配置 config: { overshootClamping: true }（禁止默认过冲回弹）。`
        );
      }
      return;
    }
    const cfgExpr = top.props.get('config');
    const cfgObj = resolveObjectLiteral(cfgExpr, constMap);
    if (!cfgObj) {
      warnings.push(
        `${loc} remotion spring() 的 config 为动态变量引用，无法静态校验 overshootClamping: true。`
      );
      return;
    }
    const cfg = inspectObject(cfgObj, constMap);
    if (!cfg.props.has('overshootClamping')) {
      if (cfg.hasUnresolvedSpread) {
        warnings.push(
          `${loc} remotion spring() 的 config 含动态展开，无法静态校验 overshootClamping: true。`
        );
      } else {
        errors.push(
          `${loc} remotion spring() 的 config 缺少 overshootClamping: true（禁止过冲回弹）。`
        );
      }
      return;
    }
    const val = unwrapExpr(cfg.props.get('overshootClamping'));
    if (val && val.kind === ts.SyntaxKind.TrueKeyword) {
      return;
    }
    if (
      val &&
      (val.kind === ts.SyntaxKind.FalseKeyword ||
        val.kind === ts.SyntaxKind.NullKeyword ||
        val.kind === ts.SyntaxKind.UndefinedKeyword ||
        ts.isLiteralExpression(val))
    ) {
      errors.push(`${loc} remotion spring() 的 config.overshootClamping 必须为 true。`);
      return;
    }
    warnings.push(
      `${loc} remotion spring() 的 config.overshootClamping 为动态表达式，无法静态确认为 true。`
    );
  }

  function walk(node) {
    if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
    ) {
      checkStringNode(node, node.text);
    } else if (ts.isCallExpression(node) && (springIds.size || remotionNamespaces.size)) {
      const callee = unwrapExpr(node.expression);
      const isDirectSpring = ts.isIdentifier(callee) && springIds.has(callee.text);
      const isNsSpring =
        ts.isPropertyAccessExpression(callee) &&
        ts.isIdentifier(callee.expression) &&
        remotionNamespaces.has(callee.expression.text) &&
        callee.name.text === 'spring';
      if (isDirectSpring || isNsSpring) {
        checkSpringCall(node);
      }
    }
    ts.forEachChild(node, walk);
  }

  walk(sf);
  return {errors, warnings};
}

function lintProgram(program, entryFile, baseDir) {
  const entryDir = path.dirname(path.resolve(entryFile)) + path.sep;
  const vendorVibeDir = path.join(path.dirname(path.resolve(entryFile)), 'vendor', 'vibe') + path.sep;
  const errors = [];
  const warnings = [];
  for (const sf of program.getSourceFiles()) {
    if (sf.isDeclarationFile) continue;
    const resolved = path.resolve(sf.fileName);
    if (!resolved.startsWith(entryDir)) continue;
    if (resolved.startsWith(vendorVibeDir)) continue;
    if (resolved.includes(path.sep + 'node_modules' + path.sep)) continue;
    const res = lintSourceFile(sf, baseDir);
    errors.push(...res.errors);
    warnings.push(...res.warnings);
  }
  return {errors, warnings};
}

function main() {
  const root = path.resolve(__dirname, '..');
  const project = require(path.join(root, 'package.json'));

  if (!semver.satisfies(process.versions.node, project.engines.node)) {
    throw Error('Node ' + process.versions.node + ' does not match ' + project.engines.node);
  }
  if (require('remotion/package.json').version !== project.dependencies.remotion) {
    throw Error('Remotion installation differs from package.json');
  }
  require('@remotion/bundler');
  require('@remotion/renderer');
  require('./render_episode.cjs');
  const configPath = path.join(root, 'tsconfig.json');
  const source = ts.readConfigFile(configPath, ts.sys.readFile);
  if (source.error) throw Error(ts.flattenDiagnosticMessageText(source.error.messageText, '\n'));
  const converted = ts.convertCompilerOptionsFromJson(source.config.compilerOptions, root);
  const options = {
    ...converted.options,
    noEmit: true,
    resolveJsonModule: true,
    jsx: ts.JsxEmit.ReactJSX,
    lib: ['lib.es2022.d.ts', 'lib.dom.d.ts', 'lib.dom.iterable.d.ts'],
  };
  const entryPath = path.resolve(process.argv[2]);
  const program = ts.createProgram([entryPath], options);
  const liveCore = path.join(root, 'core', 'vibe') + path.sep;
  if (program.getSourceFiles().some((file) => path.resolve(file.fileName).startsWith(liveCore))) {
    throw Error('Import the episode snapshot in src/vendor/vibe');
  }
  const errors = [...converted.errors, ...ts.getPreEmitDiagnostics(program)];
  if (errors.length) {
    console.error(
      ts.formatDiagnosticsWithColorAndContext(errors, {
        getCanonicalFileName: (name) => name,
        getCurrentDirectory: () => root,
        getNewLine: () => '\n',
      })
    );
    process.exitCode = 1;
  }
  const lint = lintProgram(program, entryPath, root);
  for (const msg of lint.warnings) {
    console.error(`[vibe-lint][WARN] ${msg}`);
  }
  for (const msg of lint.errors) {
    console.error(`[vibe-lint][ERROR] ${msg}`);
  }
  if (lint.errors.length) {
    process.exitCode = 1;
  }
}

if (require.main === module) {
  main();
}

module.exports = {lintProgram, lintSourceFile};
