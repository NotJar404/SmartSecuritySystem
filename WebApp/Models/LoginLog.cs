using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace SmartSecuritySystem.Models
{
    [Table("login_logs")]
    public class LoginLog
    {
        [Key]
        [Column("log_id")]
        public int LogId { get; set; }

        [Column("username")]
        [MaxLength(50)]
        public string? Username { get; set; }

        [Column("ip_address")]
        [MaxLength(50)]
        public string? IpAddress { get; set; }

        [Column("success")]
        public bool Success { get; set; }

        [Column("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    }
}