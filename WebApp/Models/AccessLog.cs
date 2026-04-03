using System;

namespace WebApp.Models
{
    public class AccessLog
    {
        public int Id { get; set; }

        // ================= BASIC INFO =================
        public string FullName { get; set; }
        public string StudentId { get; set; }

        // ================= USER DETAILS =================
        public string Department { get; set; }
        public string Email { get; set; }
        public string Phone { get; set; }

        // ================= ACCESS INFO =================
        public string Room { get; set; }
        public string Location { get; set; }
        public DateTime Timestamp { get; set; }

        // ================= SECURITY =================
        public bool IsAuthorized { get; set; }   // Final result
        public bool RFIDMatched { get; set; }    // RFID success
        public bool FaceMatched { get; set; }    // Face verification

        // ================= MEDIA =================
        public string ImageUrl { get; set; }

        // ================= HELPER (OPTIONAL BUT USEFUL) =================
        public string Status
        {
            get
            {
                if (IsAuthorized) return "Authorized";
                return "Denied";
            }
        }

        public string StatusColor
        {
            get
            {
                return IsAuthorized ? "green" : "red";
            }
        }
    }
}