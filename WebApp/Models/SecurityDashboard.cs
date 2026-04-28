using System.Collections.Generic;

namespace WebApp.Models
{
    public class DashboardViewModel
    {
        public int ActiveCameraCount { get; set; }
        public int TotalCameraCount { get; set; }

        public int TodayDetectionCount { get; set; }
        public int ActiveAlertCount { get; set; }
        public int PendingAccessCount { get; set; }

        // =====================
        // EXISTING DATA
        // =====================

        public List<DetectionLog> RecentEvents { get; set; } = new();
        public List<Camera> Cameras { get; set; } = new();

        // =====================
        // 🔥 ADD THIS (FIX ERROR)
        // =====================

        public List<AccessLog> RecentAccessLogs { get; set; } = new();
        public List<Alert> RecentAlerts { get; set; } = new();
    }
}