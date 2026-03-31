using System;
using System.ComponentModel.DataAnnotations;

namespace SmartSecuritySystem.Models
{
    public class User
    {
        public int Id { get; set; }

        [Required]
        [StringLength(50)]
        public string Username { get; set; } = string.Empty;

        // 🔥 FIXED: Use PasswordHash instead of Password
        [Required]
        public string PasswordHash { get; set; } = string.Empty;

        [Required]
        public string Role { get; set; } = "Security"; // default role

        [Required]
        [StringLength(100)]
        public string Name { get; set; } = string.Empty;

        [Required]
        [EmailAddress]
        public string Email { get; set; } = string.Empty;

        public string Status { get; set; } = "Active";

        public DateTime? LastLogin { get; set; }

        // 🔥 PROFILE IMAGE
        public string? ProfileImagePath { get; set; }
    }
}