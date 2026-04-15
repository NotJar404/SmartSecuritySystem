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

        public List<DetectionLog> RecentEvents { get; set; } = new();

        // ✅ FIXED HERE
        public List<Camera> Cameras { get; set; } = new();
    }
}