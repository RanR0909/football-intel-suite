import axios from "axios"
import { toast } from "sonner"

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || "/api",
  timeout: 15000,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg =
      err.response?.data?.error ||
      err.response?.data?.message ||
      err.message ||
      "请求失败"
    if (!err.config?.silenceErrorToast) {
      toast.error(msg)
    }
    return Promise.reject(err)
  }
)
