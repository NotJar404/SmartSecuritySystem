namespace WebApp.Models
{
    public class Alert
    {
        public int Id { get; set; }
        public string Title { get; set; }           // "Unauthorized Person"
        public string Description { get; set; }     // Details
        public string Location { get; set; }        // Front Door, Back Yard
        public string Severity { get; set; }        // CRITICAL, WARNING
        public string Status { get; set; }          // Active, Resolved
        public DateTime CreatedAt { get; set; }
    }
}