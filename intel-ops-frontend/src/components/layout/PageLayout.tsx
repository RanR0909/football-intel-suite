import { Outlet } from "react-router-dom"
import Sidebar from "./Sidebar"

export default function PageLayout() {
  return (
    <div className="min-h-screen flex bg-background">
      <Sidebar />
      <main className="flex-1 min-w-0 px-6 py-5 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
