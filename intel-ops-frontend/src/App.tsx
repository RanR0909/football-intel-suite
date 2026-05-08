import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "react-router-dom"
import { Toaster } from "sonner"
import { router } from "@/router"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // staleTime 60s：sync 跑完最多 1 分钟内前端能看到新数据
      // refetchOnMount/Focus 'always'：切回 tab 或路由切换都强制拉一遍
      // 这两个一起作用 → 后台 launchd 跑完，前端打开/切页就刷
      staleTime: 60 * 1000,
      retry: 1,
      refetchOnMount: "always",
      refetchOnWindowFocus: "always",
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  )
}
