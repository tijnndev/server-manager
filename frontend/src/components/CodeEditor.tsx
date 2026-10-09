import { useEffect } from "react";
import Editor, { loader, type OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import editorWorker from "../../node_modules/monaco-editor/esm/vs/editor/editor.worker.js?worker";
import cssWorker from "../../node_modules/monaco-editor/esm/vs/language/css/css.worker.js?worker";
import htmlWorker from "../../node_modules/monaco-editor/esm/vs/language/html/html.worker.js?worker";
import jsonWorker from "../../node_modules/monaco-editor/esm/vs/language/json/json.worker.js?worker";
import tsWorker from "../../node_modules/monaco-editor/esm/vs/language/typescript/ts.worker.js?worker";

// Bundle Monaco locally (no CDN dependency) and wire up the web workers.
self.MonacoEnvironment = {
  getWorker(_workerId: string, label: string) {
    switch (label) {
      case "json":
        return new jsonWorker();
      case "css":
      case "scss":
      case "less":
        return new cssWorker();
      case "html":
      case "handlebars":
      case "razor":
        return new htmlWorker();
      case "typescript":
      case "javascript":
        return new tsWorker();
      default:
        return new editorWorker();
    }
  },
};

loader.config({ monaco });

/** Dark theme matching the panel design tokens. */
const SM_DARK = "sm-dark";

function defineTheme() {
  monaco.editor.defineTheme(SM_DARK, {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "6d7480", fontStyle: "italic" },
      { token: "string", foreground: "8fd6a8" },
      { token: "number", foreground: "d9b06c" },
      { token: "keyword", foreground: "7ca7f5" },
      { token: "type", foreground: "a3aab6" },
      { token: "tag", foreground: "7ca7f5" },
      { token: "attribute.name", foreground: "d9b06c" },
      { token: "attribute.value", foreground: "8fd6a8" },
      { token: "delimiter", foreground: "a3aab6" },
      { token: "variable", foreground: "e7eaef" },
      { token: "key", foreground: "7ca7f5" },
    ],
    colors: {
      "editor.background": "#0a0c0f",
      "editor.foreground": "#e7eaef",
      "editorLineNumber.foreground": "#4a5058",
      "editorLineNumber.activeForeground": "#a3aab6",
      "editor.selectionBackground": "#2c4a7a",
      "editor.lineHighlightBackground": "#13161b",
      "editorCursor.foreground": "#5c8dff",
      "editorIndentGuide.background": "#1d2129",
      "editorIndentGuide.activeBackground": "#2f3540",
      "scrollbarSlider.background": "#32384580",
      "scrollbarSlider.hoverBackground": "#3d445080",
      "scrollbarSlider.activeBackground": "#4a526080",
      "editorWidget.background": "#16191e",
      "editorWidget.border": "#323845",
      "editorSuggestWidget.background": "#16191e",
      "editorSuggestWidget.border": "#323845",
      "editorSuggestWidget.selectedBackground": "#1d2129",
      "editorHoverWidget.background": "#16191e",
      "editorHoverWidget.border": "#323845",
    },
  });
}

const EXT_LANGUAGE: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  json: "json",
  jsonc: "json",
  yaml: "yaml",
  yml: "yaml",
  html: "html",
  htm: "html",
  css: "css",
  scss: "scss",
  less: "less",
  md: "markdown",
  markdown: "markdown",
  py: "python",
  go: "go",
  rs: "rust",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  sql: "sql",
  xml: "xml",
  svg: "xml",
  toml: "ini",
  ini: "ini",
  conf: "ini",
  cfg: "ini",
  env: "ini",
  php: "php",
  rb: "ruby",
  java: "java",
  c: "c",
  h: "c",
  cpp: "cpp",
  hpp: "cpp",
  cs: "csharp",
  vue: "html",
  svelte: "html",
  dockerfile: "dockerfile",
  lock: "ini",
  log: "log",
  txt: "plaintext",
};

/** Detect the Monaco language id from a file path or name. */
export function detectLanguage(path: string): string {
  const name = path.split("/").pop() ?? path;
  const lower = name.toLowerCase();
  if (lower === "dockerfile" || lower.startsWith("dockerfile.")) return "dockerfile";
  if (lower.endsWith(".d.ts") || lower.endsWith(".d.js")) return "typescript";
  if (lower === ".gitignore" || lower === ".dockerignore" || lower === ".env" || lower.startsWith(".env.")) return "ini";
  const ext = lower.includes(".") ? lower.split(".").pop()! : "";
  return EXT_LANGUAGE[ext] ?? "plaintext";
}

export function CodeEditor({
  path,
  value,
  onChange,
  readOnly = false,
  height = 460,
}: {
  path: string;
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  height?: number;
}) {
  useEffect(defineTheme, []);

  const onMount: OnMount = (editor) => {
    editor.focus();
  };

  return (
    <Editor
      language={detectLanguage(path)}
      theme={SM_DARK}
      value={value}
      onChange={(v) => onChange?.(v ?? "")}
      onMount={onMount}
      height={height}
      loading={
        <div style={{ display: "grid", placeItems: "center", height: "100%" }}>
          <span className="muted">Loading editor…</span>
        </div>
      }
      options={{
        readOnly,
        fontFamily: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
        fontSize: 12.5,
        lineHeight: 1.6,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        smoothScrolling: true,
        padding: { top: 12, bottom: 12 },
        renderLineHighlight: "line",
        cursorBlinking: "smooth",
        automaticLayout: true,
        tabSize: 2,
        wordWrap: "on",
        overviewRulerLanes: 0,
        scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
      }}
    />
  );
}
