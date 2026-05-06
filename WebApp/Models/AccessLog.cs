using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("access_logs")]
    public class AccessLog
    {
        // =========================
        // PRIMARY KEY
        // =========================
        [Key]
        [Column("log_id")]
        public int LogId { get; set; }

        // =========================
        // RELATIONSHIPS
        // =========================
        [Column("person_id")]
        public int? PersonId { get; set; }

        [ForeignKey("PersonId")]
        public AuthorizedPersonnel? Person { get; set; }

        [Column("room_id")]
        public int? RoomId { get; set; }

        [ForeignKey("RoomId")]
        public Room? RoomEntity { get; set; }

        // =========================
        // SECURITY INPUT DATA
        // =========================
        [Column("rfid_valid")]
        public bool RfidValid { get; set; }

        [Column("face_verified")]
        public bool FaceVerified { get; set; }

        [Column("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        // =========================
        // FINAL SYSTEM DECISION (DB STORED)
        // =========================
        [Column("access_result")]
        public string AccessResult { get; set; } = "PENDING";

        // =========================
        // VIDEO EVIDENCE
        // =========================
        [Column("video_path")]
        public string? VideoPath { get; set; }

        // =========================
        // UI HELPERS (SAFE DEFAULTS ADDED → FIXES CS8618)
        // =========================

        [NotMapped]
        public string FullName { get; set; } = "";

        [NotMapped]
        public string PersonnelId { get; set; } = "";

        [NotMapped]
        public string Department { get; set; } = "";

        [NotMapped]
        public string Email { get; set; } = "";

        [NotMapped]
        public string Phone { get; set; } = "";

        [NotMapped]
        public string ImageUrl { get; set; } = "/images/default-user.png";

        [NotMapped]
        public string Room { get; set; } = "";

        [NotMapped]
        public string Location { get; set; } = "";

        // =========================
        // UI LOGIC HELPERS
        // =========================
        [NotMapped]
        public bool HasVideo => !string.IsNullOrEmpty(VideoPath);

        [NotMapped]
        public string StatusColor => AccessResult switch
        {
            "AUTHORIZED" => "#2ecc71",
            "SUSPICIOUS" => "#f39c12",
            "UNAUTHORIZED" => "#e74c3c",
            _ => "#95a5a6"
        };

        [NotMapped]
        public bool IsAuthorized => AccessResult == "AUTHORIZED";

        [NotMapped]
        public bool IsSuspicious => AccessResult == "SUSPICIOUS";

        [NotMapped]
        public bool IsUnauthorized => AccessResult == "UNAUTHORIZED";

        // =========================
        // AI RISK ENGINE (READ ONLY)
        // =========================
        [NotMapped]
        public string ComputedRiskLevel
        {
            get
            {
                if (!RfidValid && !FaceVerified)
                    return "UNAUTHORIZED";

                if (!RfidValid || !FaceVerified)
                    return "SUSPICIOUS";

                return "AUTHORIZED";
            }
        }
    }
}