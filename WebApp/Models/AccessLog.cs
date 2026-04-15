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
        // UI HELPERS
        // =========================

        [NotMapped]
        public bool IsAuthorized
        {
            get => string.Equals(AccessResult ?? "denied", "granted", StringComparison.OrdinalIgnoreCase);
            set => AccessResult = value ? "granted" : "denied";
        }

        [NotMapped]
        public string Status
        {
            get => IsAuthorized ? "Authorized" : "Denied";
        }

        [NotMapped]
        public string StatusColor =>
            IsAuthorized ? "green" : "red";

        [NotMapped]
        public int Id
        {
            get => LogId;
            set => LogId = value;
        }

        [NotMapped]
        public bool RFIDMatched
        {
            get => RfidValid;
            set => RfidValid = value;
        }

        [NotMapped]
        public bool FaceMatched
        {
            get => FaceVerified;
            set => FaceVerified = value;
        }

        [NotMapped] public string? FullName { get; set; }
        [NotMapped] public string? StudentId { get; set; }
        [NotMapped] public string? Department { get; set; }
        [NotMapped] public string? Email { get; set; }
        [NotMapped] public string? Phone { get; set; }
        [NotMapped] public string? ImageUrl { get; set; }
        [NotMapped] public string? Room { get; set; }
        [NotMapped] public string? Location { get; set; }
    }
}