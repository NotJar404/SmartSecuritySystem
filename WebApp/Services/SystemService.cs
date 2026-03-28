using WebApp.Models;

namespace WebApp.Services
{
    public class SystemService
    {
        public SystemStatus GetSystemStatus()
        {
            // TODO: Replace with real data (IoT, MQTT, DB)
            return new SystemStatus
            {
                CpuUsage = 34,
                MemoryUsage = "2.4 GB / 8 GB",
                Storage = "234 GB / 500 GB",
                GpuUsage = 67,

                ConnectionStatus = "Online",
                Bandwidth = "24 Mbps",
                Latency = "12ms",
                PacketLoss = "0%",

                TotalCameras = 8,
                ActiveCameras = 7,
                OfflineCameras = 1,
                RecordingCameras = 7,

                TotalSpace = "500 GB",
                UsedSpace = "234 GB",
                Recordings = 1234,
                RetentionDays = 30,

                NotificationsEnabled = true,
                RecordingEnabled = true,
                AiDetectionEnabled = true
            };
        }

        public void UpdateSetting(string setting, bool value)
        {
            // TODO: Save to DB
            Console.WriteLine($"{setting} updated to {value}");
        }
    }
}