using System;
using System.Collections.Generic;
using WebApp.Models;

namespace WebApp.Models
{
    public class AdminDashboardViewModel
    {
        // =====================
        // DASHBOARD STATS
        // =====================

        public int ActivePersonnelCount { get; set; }
        public int ActiveCameraCount { get; set; }
        public int ActiveIncidentCount { get; set; }
        public int TodayDetectionCount { get; set; }

        // =====================
        // CHART DATA (WEEKLY)
        // =====================

        public List<int> AlertWeekly { get; set; } = new();
        public List<int> AccessWeekly { get; set; } = new();
        public List<int> MotionWeekly { get; set; } = new();
        public List<int> OccupancyWeekly { get; set; } = new();

        // FIXED: align with DayOfWeek enum order
        public List<string> Labels { get; set; } = new()
        {
            "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"
        };
    }
}