using System;
using WebApp.Models;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace SmartSecuritySystem.Models
{
    [Table("users")]
    public class User
    {
        // 🔥 FIX: prevent MVC binding crash on empty string
        [Key]
        [Column("user_id")]
        public int Id { get; set; }

        [Required]
        [Column("username")]
        [MaxLength(50)]
        public string Username { get; set; } = string.Empty;

        [Required]
        [Column("password_hash")]
        public string PasswordHash { get; set; } = string.Empty;

        // Role is controlled by backend (not user input)
        [Column("role")]
        [MaxLength(20)]
        public string Role { get; set; } = "Security";

        [Required]
        [Column("full_name")]
        [MaxLength(100)]
        public string FullName { get; set; } = string.Empty;

        [Required]
        [Column("email")]
        [MaxLength(150)]
        [EmailAddress]
        public string Email { get; set; } = string.Empty;

        [Required]
        [Column("status")]
        [MaxLength(20)]
        public string Status { get; set; } = "Active";

        [Column("last_login")]
        public DateTime? LastLogin { get; set; }

        [Column("created_at")]
        public DateTime? CreatedAt { get; set; }

        [Column("profile_image_path")]
        public string? ProfileImagePath { get; set; }

        [Column("updated_at")]
        public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
    }
}