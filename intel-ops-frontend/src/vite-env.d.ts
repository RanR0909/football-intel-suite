/// <reference types="vite/client" />

/** 显式声明项目自定义的 import.meta.env 变量
 *  vite 默认 ImportMetaEnv 是 Record<string, any>；这里收紧类型，
 *  让 lib/api.ts 等文件用到 VITE_API_BASE 时有提示 + 拼写错误能被 tsc 抓到。
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
