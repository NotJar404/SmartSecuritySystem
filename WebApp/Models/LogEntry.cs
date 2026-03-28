namespace WebApp.Models
{
    public class LogEntry
    {
        public int Id { get; set; }
        public string Action { get; set; }      // "Login", "Camera Added"
        public string User { get; set; }        // "John Doe"
        public string Details { get; set; }     // Extra info
        public string IpAddress { get; set; }
        public DateTime Timestamp { get; set; }
    }
}