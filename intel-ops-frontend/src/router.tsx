import { createBrowserRouter, Navigate } from "react-router-dom"
import PageLayout from "@/components/layout/PageLayout"

import Overview from "@/pages/Overview"
import AlertCenter from "@/pages/AlertCenter"

import Rankings from "@/pages/data/Rankings"
import Revenue from "@/pages/data/Revenue"
import IAP from "@/pages/data/IAP"
import Website from "@/pages/data/Website"

import Releases from "@/pages/content/Releases"
import GPReviews from "@/pages/content/GPReviews"
import Social from "@/pages/content/Social"
import News from "@/pages/content/News"
import Ads from "@/pages/content/Ads"

import Candidates from "@/pages/system/Candidates"
import FailedJobs from "@/pages/system/FailedJobs"
import SyncLog from "@/pages/system/SyncLog"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <PageLayout />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: "overview", element: <Overview /> },
      { path: "alerts", element: <AlertCenter /> },

      // 数据类
      { path: "data/rankings", element: <Rankings /> },
      { path: "data/revenue", element: <Revenue /> },
      { path: "data/iap", element: <IAP /> },
      { path: "data/website", element: <Website /> },

      // 内容类
      { path: "content/releases", element: <Releases /> },
      { path: "content/gp-reviews", element: <GPReviews /> },
      { path: "content/social", element: <Social /> },
      { path: "content/news", element: <News /> },
      { path: "content/ads", element: <Ads /> },

      // 系统
      { path: "system/candidates", element: <Candidates /> },
      { path: "system/failed-jobs", element: <FailedJobs /> },
      { path: "system/sync-log", element: <SyncLog /> },
    ],
  },
])
