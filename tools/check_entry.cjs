// Check only this episode and its transitive imports, using the installed compiler.
const path = require('node:path');
const ts = require('typescript');
const semver = require('semver');
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
const options = {...converted.options, noEmit:true, resolveJsonModule:true, jsx:ts.JsxEmit.ReactJSX,
  lib:['lib.es2022.d.ts','lib.dom.d.ts','lib.dom.iterable.d.ts']};
const program = ts.createProgram([path.resolve(process.argv[2])], options);
const liveCore = path.join(root, 'core', 'vibe') + path.sep;
if (program.getSourceFiles().some(file => path.resolve(file.fileName).startsWith(liveCore))) {
  throw Error('Import the episode snapshot in src/vendor/vibe');
}
const errors = [...converted.errors, ...ts.getPreEmitDiagnostics(program)];
if (errors.length) {
  console.error(ts.formatDiagnosticsWithColorAndContext(errors, {
    getCanonicalFileName:name=>name, getCurrentDirectory:()=>root, getNewLine:()=>'\n',
  }));
  process.exitCode = 1;
}
