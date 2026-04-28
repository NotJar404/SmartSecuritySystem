using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("access_logs")]
    public class AccessLog
    {
        [Key]
        [Column("log_id")]
        public int LogId { get; set; }

        [Column("person_id")]
        public int? PersonId { get; set; }

        [Column("room_id")]
        public int? RoomId { get; set; }

        [Column("access_result")]
        public string AccessResult { get; set; } = "denied";

        [Column("rfid_valid")]
        public bool RfidValid { get; set; }

        [Column("face_verified")]
        public bool FaceVerified { get; set; }

        [Column("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        // =========================
        // NEW: VIDEO LINKING
        // =========================
        
        [Column("video_path")]
        public string? VideoPath { get; set; }

        // =========================
        // UI HELPERS (NOT IN DB)
        // =========================

        [NotMapped]
        public bool IsAuthorized
        {
            get => string.Equals(AccessResult ?? "denied", "granted", StringComparison.OrdinalIgnoreCase);
            set => AccessResult = value ? "granted" : "denied";
        }

        [NotMapped]
        public string Status => IsAuthorized ? "Authorized" : "Denied";

        [NotMapped]
        public string StatusColor => IsAuthorized ? "#2ecc71" : "#e74c3c"; // Using Hex for premium UI colors

        [NotMapped]
        public bool HasVideo => !string.IsNullOrEmpty(VideoPath);

        // ==========================================
        // JOINED DATA (Populated via SQL/Controller)
        // ==========================================

        [NotMapped] public string? FullName { get; set; }
        
        [NotMapped] public string? PersonnelId { get; set; } // Renamed from StudentId
        
        [NotMapped] public string? Department { get; set; }
        
        [NotMapped] public string? Email { get; set; }
        
        [NotMapped] public string? Phone { get; set; }
        
        [NotMapped] public string? ImageUrl { get; set; }
        
        [NotMapped] public string? Room { get; set; }
        
        [NotMapped] public string? Location { get; set; }
    }
}