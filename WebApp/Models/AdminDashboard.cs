using System;
using System.Collections.Generic;

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

        // =====================
        // LABELS
        // =====================
        public List<string> Labels { get; set; } = new()
        {
            "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"
        };

        // =====================
        // AUDIT LOGS (NEW)
        // =====================
        public List<AuditLogViewModel> AuditLogs { get; set; } = new();

        // =====================
        // ACTIVE INTERVENTIONS
        // =====================
        public List<Alert> ActiveInterventions { get; set; } = new();
    }

    // =====================
    // SUPPORTING MODEL
    // =====================
    public class AuditLogViewModel
    {
        public string Action { get; set; } = "";
        public string Description { get; set; } = "";
        public DateTime Timestamp { get; set; }
    }
}