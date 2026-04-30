import { NavLink } from "react-router-dom"
import {
  LayoutDashboard, AlertCircle,
  TrendingUp, DollarSign, Tag, Globe,
  GitBranch, MessageSquare, Hash, Newspaper, Megaphone,
  Search, AlertTriangle, ScrollText,
  PanelLeftClose, PanelLeftOpen, Sun, Moon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useGlobalStore } from "@/stores/globalStore"
import { useStatus } from "@/hooks/api/useDashboardData"

interface NavItem {
  to: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  badge?: () => number | undefined
}

interface NavGroup {
  title?: string
  items: NavItem[]
}

export default function Sidebar() {
  const { sidebarCollapsed, toggleSidebar, theme, setTheme } = useGlobalStore()
  const { data: status } = useStatus()

  const groups: NavGroup[] = [
    {
      items: [
        { to: "/overview", label: "总览看点", icon: LayoutDashboard },
        { to: "/alerts", label: "预警中心", icon: AlertCircle,
          badge: () => status?.alerts_new_7d },
      ],
    },
    {
      title: "数据类",
      items: [
        { to: "/data/rankings", label: "排名异动", icon: TrendingUp },
        { to: "/data/revenue", label: "收入下载", icon: DollarSign },
        { to: "/data/iap", label: "IAP 内购", icon: Tag },
        { to: "/data/website", label: "网站数据", icon: Globe },
      ],
    },
    {
      title: "内容类",
      items: [
        { to: "/content/releases", label: "产品动态", icon: GitBranch },
        { to: "/content/gp-reviews", label: "GP 评论", icon: MessageSquare },
        { to: "/content/social", label: "社媒评论", icon: Hash },
        { to: "/content/news", label: "商业新闻", icon: Newspaper },
        { to: "/content/ads", label: "广告投放", icon: Megaphone },
      ],
    },
    {
      title: "系统",
      items: [
        { to: "/system/candidates", label: "候选发现", icon: Search,
          badge: () => status?.candidates_count },
        { to: "/system/failed-jobs", label: "AI 失败队列", icon: AlertTriangle,
          badge: () => Object.values(status?.failed_ai_jobs || {})
            .reduce((a, b) => a + (b || 0), 0) || undefined },
        { to: "/system/sync-log", label: "同步日志", icon: ScrollText },
      ],
    },
  ]

  return (
    <aside className={cn(
      "border-r border-border-soft bg-background transition-all duration-150 shrink-0",
      sidebarCollapsed ? "w-14" : "w-56"
    )}>
      <div className="h-12 px-3 flex items-center justify-between border-b border-border-soft">
        {!sidebarCollapsed && (
          <span className="text-sm font-semibold tracking-tight">
            INTEL-OPS
          </span>
        )}
        <button
          onClick={toggleSidebar}
          className="p-1 rounded hover:bg-muted text-muted-foreground"
          title={sidebarCollapsed ? "展开" : "收起"}
        >
          {sidebarCollapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
        </button>
      </div>

      <nav className="px-2 py-2 space-y-3">
        {groups.map((group, gi) => (
          <div key={gi}>
            {group.title && !sidebarCollapsed && (
              <div className="px-2 pb-1 text-2xs uppercase tracking-wider text-muted-foreground">
                {group.title}
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const badge = item.badge?.()
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 px-2 h-8 rounded text-sm transition-colors duration-150",
                        isActive
                          ? "bg-brand-50 text-brand-700 font-medium dark:bg-brand-900/20 dark:text-brand-300"
                          : "text-foreground/80 hover:bg-muted/50"
                      )
                    }
                  >
                    <item.icon className="w-4 h-4 shrink-0" />
                    {!sidebarCollapsed && (
                      <>
                        <span className="flex-1 truncate">{item.label}</span>
                        {badge != null && badge > 0 && (
                          <span className="px-1.5 h-4 min-w-4 inline-flex items-center justify-center rounded bg-semantic-danger text-white text-2xs font-medium">
                            {badge > 99 ? "99+" : badge}
                          </span>
                        )}
                      </>
                    )}
                  </NavLink>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      {!sidebarCollapsed && (
        <div className="absolute bottom-0 left-0 w-56 px-2 py-2 border-t border-border-soft">
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="w-full flex items-center gap-2 px-2 h-8 rounded text-sm text-muted-foreground hover:bg-muted/50"
          >
            {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            <span>{theme === "dark" ? "亮色" : "暗色"}模式</span>
          </button>
        </div>
      )}
    </aside>
  )
}
