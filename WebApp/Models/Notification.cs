using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("notifications")]
    public class Notification
    {
        [Key]
        [Column("notification_id")]
        public int NotificationId { get; set; }

        // =========================================
        // RELATION LINKS
        // =========================================
        [Column("alert_id")]
        public int? AlertId { get; set; }

        [ForeignKey("AlertId")]
        public Alert? Alert { get; set; }   // safe navigation property

        [Column("log_id")]
        public int? LogId { get; set; }

        // =========================================
        // TARGET USER / ROLE DELIVERY
        // =========================================
        [Column("user_id")]
        public int? UserId { get; set; }

        [Column("target_role")]
        public string? TargetRole { get; set; }
        // admin | security | null = system-wide

        // =========================================
        // CONTENT
        // =========================================
        [Column("message")]
        public string Message { get; set; } = string.Empty;

        // =========================================
        // STATUS
        // =========================================
        [Column("is_read")]
        public bool IsRead { get; set; } = false;

        [Column("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        // =========================================
        // UI HELPERS (NOT DB FIELDS)
        // =========================================

        [NotMapped]
        public string Type
        {
            get
            {
                if (AlertId.HasValue) return "alert";
                if (LogId.HasValue) return "access";
                return "system";
            }
        }

        // 🔥 FIXED: NO enum/string mismatch anymore
        [NotMapped]
        public string Priority
        {
            get
            {
                if (Alert != null)
                    return Alert.Severity.ToString().ToLower();

                if (LogId.HasValue)
                    return "info";

                return "system";
            }
        }

        [NotMapped]
        public string Title
        {
            get
            {
                if (Alert != null)
                    return Alert.Type.ToString();   // safe enum → string

                if (!string.IsNullOrEmpty(Message))
                    return Message;

                return "System Notification";
            }
        }

        [NotMapped]
        public bool IsSystemWide =>
            UserId == null && TargetRole == null;
    }
}