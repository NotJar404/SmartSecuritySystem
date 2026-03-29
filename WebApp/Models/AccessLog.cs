using System;

namespace WebApp.Models
{
    public class AccessLog
    {
        public int Id { get; set; }

        public string FullName { get; set; }
        public string StudentId { get; set; }

        public string Location { get; set; }
        public DateTime Timestamp { get; set; }

        public bool IsAuthorized { get; set; } // RFID + Face result
        public string ImageUrl { get; set; }
    }
}