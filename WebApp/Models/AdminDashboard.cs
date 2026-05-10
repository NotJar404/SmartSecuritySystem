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
        // ENHANCED CHART DATA
        // =====================
        /// <summary>
        /// Alert breakdown by type (Intrusion, UnauthorizedAccess, SuspiciousActivity, etc.)
        /// Used for doughnut/pie chart display
        /// </summary>
        public Dictionary<string, int> AlertsByType { get; set; } = new();

        /// <summary>
        /// Alert trends by day (Sun-Sat) and type for stacked bar chart
        /// Structure: { "Mon": { "Intrusion": 3, "UnauthorizedAccess": 2 }, ... }
        /// </summary>
        public Dictionary<string, Dictionary<string, int>> AlertTrendsByDayAndType { get; set; } = new();

        /// <summary>
        /// Occupancy per room (room name → total people counted)
        /// Used for horizontal bar chart display
        /// </summary>
        public List<string> OccupancyRoomLabels { get; set; } = new();
        public List<int> OccupancyRoomCounts { get; set; } = new();

        /// <summary>
        /// Access breakdown: Authorized, Suspicious, Unauthorized
        /// Used for doughnut chart display
        /// </summary>
        public Dictionary<string, int> AccessByResult { get; set; } = new();

        /// <summary>
        /// Detection breakdown by type (person, face, motion, etc.)
        /// Used for polar/radar chart display
        /// </summary>
        public Dictionary<string, int> DetectionsByType { get; set; } = new();

        /// <summary>
        /// Available rooms for dynamic dropdown filter
        /// </summary>
        public List<Room> AvailableRooms { get; set; } = new();

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
        public string User { get; set; } = "";
        public DateTime Timestamp { get; set; }
    }
}