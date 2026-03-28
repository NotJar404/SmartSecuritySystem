namespace WebApp.Models
{
    public class SystemStatus
    {
        // Hardware
        public int CpuUsage { get; set; }
        public string MemoryUsage { get; set; }
        public string Storage { get; set; }
        public int GpuUsage { get; set; }

        // Network
        public string ConnectionStatus { get; set; }
        public string Bandwidth { get; set; }
        public string Latency { get; set; }
        public string PacketLoss { get; set; }

        // Cameras
        public int TotalCameras { get; set; }
        public int ActiveCameras { get; set; }
        public int OfflineCameras { get; set; }
        public int RecordingCameras { get; set; }

        // Storage
        public string TotalSpace { get; set; }
        public string UsedSpace { get; set; }
        public int Recordings { get; set; }
        public int RetentionDays { get; set; }

        // Settings Toggles
        public bool NotificationsEnabled { get; set; }
        public bool RecordingEnabled { get; set; }
        public bool AiDetectionEnabled { get; set; }
    }
}