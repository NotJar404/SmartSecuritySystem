using System.Collections.Generic;

namespace WebApp.Models
{
    public class SystemStatus
    {
        public List<CameraDevice> Cameras { get; set; } = new();

        public bool NotificationsEnabled { get; set; } = true;
        public bool RecordingEnabled { get; set; } = true;
        public bool AiDetectionEnabled { get; set; } = true;

        public List<EmergencyAlarm> EmergencyAlarms { get; set; } = new();
    }

    public class CameraDevice
    {
        public int Id { get; set; }

        public string Name { get; set; } = string.Empty;

        public string Location { get; set; } = string.Empty;

        public string IpAddress { get; set; } = string.Empty;

        public bool IsActive { get; set; } = true;

        public bool IsRecording { get; set; } = false;
    }

    public class EmergencyAlarm
    {
        public int Id { get; set; }

        public string Name { get; set; } = string.Empty;

        public string Description { get; set; } = string.Empty;

        public string IconType { get; set; } = string.Empty;

        public bool IsEnabled { get; set; } = false;
    }
}