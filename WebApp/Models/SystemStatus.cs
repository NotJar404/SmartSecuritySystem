using System.Collections.Generic;

namespace WebApp.Models
{
    public class SystemStatus
    {
        public List<CameraDevice> Cameras { get; set; } = new List<CameraDevice>();

        public bool NotificationsEnabled { get; set; } = true;
        public bool RecordingEnabled { get; set; } = true;
        public bool AiDetectionEnabled { get; set; } = true;

        public List<EmergencyAlarm> EmergencyAlarms { get; set; } = new List<EmergencyAlarm>();
    }

    public class CameraDevice
    {
        public int Id { get; set; }
        public string Name { get; set; } = "";
        public string Location { get; set; } = "";
        public string IpAddress { get; set; } = "";
        public bool IsActive { get; set; } = true;
        public bool IsRecording { get; set; } = false;
    }

    public class EmergencyAlarm
    {
        public int Id { get; set; }
        public string Name { get; set; } = "";
        public string Description { get; set; } = "";
        public string IconType { get; set; } = "";
        public bool IsEnabled { get; set; } = false;
    }
}