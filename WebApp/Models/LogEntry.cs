namespace WebApp.Models
{
    public class LogEntry
    {
        public int Id { get; set; }

        public string? Action { get; set; } = string.Empty;

        public string? User { get; set; } = string.Empty;

        public string? Details { get; set; } = string.Empty;

        public string? IpAddress { get; set; } = string.Empty;

        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        // 🔥 IMPORTANT: used for filtering UI (Login / Access / Detection / Alert)
        public string Type { get; set; } = string.Empty;
    }
}